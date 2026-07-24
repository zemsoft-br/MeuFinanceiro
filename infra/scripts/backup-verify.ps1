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
    $stdoutPath = $null
    $stderrPath = $null
    $stdoutText = ""
    $stderrText = ""
    try {
        $ErrorActionPreference = "Continue"
        if ($Capture) {
            $stdoutPath = [System.IO.Path]::GetTempFileName()
            $stderrPath = [System.IO.Path]::GetTempFileName()
            & docker @Arguments 1> $stdoutPath 2> $stderrPath
            $exitCode = $LASTEXITCODE
            if (Test-Path -LiteralPath $stdoutPath) {
                $stdoutText = [string](
                    Get-Content -LiteralPath $stdoutPath -Raw -ErrorAction SilentlyContinue
                )
            }
            if (Test-Path -LiteralPath $stderrPath) {
                $stderrText = [string](
                    Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue
                )
            }
        }
        else {
            $output = @(& docker @Arguments 2>&1 | ForEach-Object { "$_" })
            $exitCode = $LASTEXITCODE
        }
    }
    finally {
        $ErrorActionPreference = $previousPreference
        foreach ($temporaryPath in @($stdoutPath, $stderrPath)) {
            if ($temporaryPath -and (Test-Path -LiteralPath $temporaryPath)) {
                Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
            }
        }
    }

    if ($exitCode -ne 0) {
        $stderrText = $stderrText.Trim()
        if (-not [string]::IsNullOrWhiteSpace($stderrText)) {
            Write-Warning $stderrText
        }
        throw "Comando Docker falhou com código $exitCode."
    }
    if ($Capture) {
        $stdoutText = $stdoutText.Trim()
        if ([string]::IsNullOrWhiteSpace($stdoutText)) {
            throw "Comando Docker não retornou a saída esperada."
        }
        return $stdoutText
    }
    if (-not $Quiet) {
        $output | ForEach-Object { Write-Host $_ }
    }
}

function Select-CapturedLine {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Text,
        [Parameter(Mandatory = $true)]
        [string]$Pattern,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    if ([string]::IsNullOrWhiteSpace($Text)) {
        throw "Saída Docker vazia para $Description."
    }
    $matches = @(
        $Text -split "`r?`n" |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -match $Pattern }
    )
    if ($matches.Count -ne 1) {
        throw "Saída Docker inválida para $Description."
    }
    return $matches[0]
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
$createdAt = [DateTimeOffset]::MinValue
if (-not [DateTimeOffset]::TryParse([string]$manifest.created_at, [ref]$createdAt)) {
    throw "created_at inválido."
}
if ($manifest.sensitive -ne $true) {
    throw "Bundle não está marcado como sensível."
}
if ([string]::IsNullOrWhiteSpace([string]$manifest.database.name)) {
    throw "Nome do banco ausente."
}
if ($manifest.database.dump_format -ne "postgresql-custom") {
    throw "Formato do dump incompatível."
}
if ($manifest.database.postgres_image -ne "postgres:18.4-alpine") {
    throw "Imagem PostgreSQL incompatível."
}
if ([string]::IsNullOrWhiteSpace([string]$manifest.database.schema_revision)) {
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

    # A imagem oficial usa um postmaster temporário no bootstrap e o reinicia
    # antes do servidor definitivo. Exigimos o mesmo start time em cinco
    # leituras consecutivas para não iniciar pg_restore durante esse shutdown.
    $ready = $false
    $lastPostmasterStart = ""
    $stableChecks = 0
    for ($attempt = 1; $attempt -le 90; $attempt++) {
        try {
            $startOutput = Invoke-Docker -Arguments @(
                "exec", $containerName, "psql",
                "--username", $restoreUser,
                "--dbname", $restoreDatabase,
                "--tuples-only",
                "--no-align",
                "--command", "SELECT pg_postmaster_start_time();"
            ) -Capture
            $currentPostmasterStart = Select-CapturedLine `
                -Text $startOutput `
                -Pattern '^\d{4}-\d{2}-\d{2} .+$' `
                -Description "início do postmaster"

            if ($currentPostmasterStart -eq $lastPostmasterStart) {
                $stableChecks++
            }
            else {
                $lastPostmasterStart = $currentPostmasterStart
                $stableChecks = 1
            }
            if ($stableChecks -ge 5) {
                $ready = $true
                break
            }
        }
        catch {
            $lastPostmasterStart = ""
            $stableChecks = 0
        }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) {
        throw "PostgreSQL descartável não atingiu estado estável."
    }

    $portOutput = Invoke-Docker -Arguments @(
        "inspect", "--format", "{{json .HostConfig.PortBindings}}", $containerName
    ) -Capture
    $portBindings = Select-CapturedLine `
        -Text $portOutput `
        -Pattern '^(null|\{\})$' `
        -Description "port bindings"
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

    $revisionOutput = Invoke-Docker -Arguments @(
        "exec", $containerName, "psql",
        "--username", $restoreUser,
        "--dbname", $restoreDatabase,
        "--tuples-only",
        "--no-align",
        "--command", "SELECT version_num FROM alembic_version;"
    ) -Capture
    $restoredRevision = Select-CapturedLine `
        -Text $revisionOutput `
        -Pattern '^[0-9A-Za-z_]+$' `
        -Description "revisão Alembic restaurada"
    if ($restoredRevision -ne [string]$manifest.database.schema_revision) {
        throw "A revisão Alembic restaurada não corresponde ao manifesto."
    }

    $infraOutput = Invoke-Docker -Arguments @(
        "exec", $containerName, "psql",
        "--username", $restoreUser,
        "--dbname", $restoreDatabase,
        "--tuples-only",
        "--no-align",
        "--command", "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'infra');"
    ) -Capture
    $infraExists = Select-CapturedLine `
        -Text $infraOutput `
        -Pattern '^[tf]$' `
        -Description "schema infra"
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
