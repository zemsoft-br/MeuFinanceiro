[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$BundleDirectory
)

$ErrorActionPreference = "Stop"
$BundleDir = (Resolve-Path -LiteralPath $BundleDirectory).Path

function Invoke-Docker {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [switch]$Capture,
        [switch]$Quiet
    )

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& docker @Arguments 2>&1 | ForEach-Object { "$_" })
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) {
        throw "Comando Docker falhou com código $exitCode."
    }
    if ($Capture) {
        return (($output -join "`n").Trim())
    }
    if (-not $Quiet) {
        $output | ForEach-Object { Write-Host $_ }
    }
}

function New-RandomHex([int]$ByteLength) {
    $bytes = New-Object byte[] $ByteLength
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    return -join ($bytes | ForEach-Object { $_.ToString("x2") })
}

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLowerInvariant()
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker não encontrado."
}

$manifestPath = Join-Path $BundleDir "manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "manifest.json não encontrado."
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.format -ne "meufinanceiro-foundation-backup" -or $manifest.version -ne 1) {
    throw "Contrato de backup incompatível."
}
if ($manifest.backup_id -notmatch '^meufinanceiro-\d{8}T\d{6}Z-[0-9a-f]{8}$') {
    throw "Identificador de backup inválido."
}
if ($manifest.sensitive -ne $true) {
    throw "Bundle não está marcado como sensível."
}
if ($manifest.database.dump_format -ne "postgresql-custom") {
    throw "Formato do dump incompatível."
}
if ($manifest.database.postgres_image -ne "postgres:18.4-alpine") {
    throw "Imagem PostgreSQL incompatível."
}
if ([string]::IsNullOrWhiteSpace($manifest.database.schema_revision)) {
    throw "Revisão Alembic ausente."
}

$requiredFiles = @("database.dump", "installation.env", "keyring.json")
$manifestFileNames = @($manifest.files.PSObject.Properties.Name)
if ($manifestFileNames.Count -ne $requiredFiles.Count) {
    throw "Inventário de arquivos incompatível."
}
foreach ($fileName in $requiredFiles) {
    if (-not ($manifestFileNames -contains $fileName)) {
        throw "Arquivo ausente no manifesto: $fileName"
    }
    $path = Join-Path $BundleDir $fileName
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Arquivo obrigatório ausente: $fileName"
    }
    $descriptor = $manifest.files.PSObject.Properties[$fileName].Value
    $item = Get-Item -LiteralPath $path
    if ([int64]$descriptor.size_bytes -ne [int64]$item.Length) {
        throw "Tamanho inválido: $fileName"
    }
    if ((Get-Sha256 $path) -ne [string]$descriptor.sha256) {
        throw "Integridade inválida: $fileName"
    }
}

$keyringPath = Join-Path $BundleDir "keyring.json"
$keyring = Get-Content -LiteralPath $keyringPath -Raw | ConvertFrom-Json
$keyProperties = @($keyring.keys.PSObject.Properties)
if ($keyring.version -ne 1 -or [string]::IsNullOrWhiteSpace($keyring.active_key_id)) {
    throw "Estrutura do keyring inválida."
}
if ($keyProperties.Count -eq 0 -or -not ($keyProperties.Name -contains $keyring.active_key_id)) {
    throw "Chave ativa não existe no keyring."
}
if (
    $manifest.keyring.version -ne $keyring.version -or
    $manifest.keyring.active_key_id -ne $keyring.active_key_id -or
    $manifest.keyring.key_count -ne $keyProperties.Count
) {
    throw "Metadados do keyring não correspondem ao arquivo."
}

$containerName = "meufinanceiro-backup-verify-$(New-RandomHex 4)"
$restoreUser = "restore_verify"
$restoreDatabase = "restore_verify"
$restorePassword = New-RandomHex 24
$started = $false

try {
    Invoke-Docker -Arguments @(
        "run",
        "--detach",
        "--name", $containerName,
        "--network", "none",
        "--tmpfs", "/var/lib/postgresql:rw,noexec,nosuid,size=512m",
        "--env", "POSTGRES_DB=$restoreDatabase",
        "--env", "POSTGRES_USER=$restoreUser",
        "--env", "POSTGRES_PASSWORD=$restorePassword",
        [string]$manifest.database.postgres_image
    ) -Quiet
    $started = $true

    $ready = $false
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        try {
            Invoke-Docker -Arguments @(
                "exec", $containerName, "pg_isready",
                "--username", $restoreUser,
                "--dbname", $restoreDatabase
            ) -Quiet
            $ready = $true
            break
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $ready) {
        throw "PostgreSQL descartável não ficou pronto."
    }

    $portBindings = Invoke-Docker -Arguments @(
        "inspect", "--format", "{{json .HostConfig.PortBindings}}", $containerName
    ) -Capture
    if ($portBindings -ne "null" -and $portBindings -ne "{}") {
        throw "O container de verificação publicou portas inesperadamente."
    }

    $dumpPath = Join-Path $BundleDir "database.dump"
    Invoke-Docker -Arguments @("cp", $dumpPath, "$containerName`:/tmp/database.dump") -Quiet
    Invoke-Docker -Arguments @(
        "exec", $containerName, "pg_restore",
        "--username", $restoreUser,
        "--dbname", $restoreDatabase,
        "--no-owner",
        "--no-privileges",
        "--exit-on-error",
        "/tmp/database.dump"
    ) -Quiet

    $restoredRevision = (Invoke-Docker -Arguments @(
        "exec", $containerName, "psql",
        "--username", $restoreUser,
        "--dbname", $restoreDatabase,
        "--tuples-only",
        "--no-align",
        "--command", "SELECT version_num FROM alembic_version;"
    ) -Capture).Trim()
    if ($restoredRevision -ne [string]$manifest.database.schema_revision) {
        throw "A revisão Alembic restaurada não corresponde ao manifesto."
    }

    $infraExists = (Invoke-Docker -Arguments @(
        "exec", $containerName, "psql",
        "--username", $restoreUser,
        "--dbname", $restoreDatabase,
        "--tuples-only",
        "--no-align",
        "--command", "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'infra');"
    ) -Capture).Trim()
    if ($infraExists -ne "t") {
        throw "O schema infra não foi restaurado."
    }
}
finally {
    if ($started) {
        try {
            Invoke-Docker -Arguments @("rm", "--force", $containerName) -Quiet
        }
        catch { }
    }
}

Write-Output "Backup $($manifest.backup_id) restaurado e verificado em ambiente descartável."
