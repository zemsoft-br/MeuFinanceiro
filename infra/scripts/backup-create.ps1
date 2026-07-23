[CmdletBinding()]
param(
    [string]$OutputDirectory,
    [switch]$AcknowledgeSensitive
)

$ErrorActionPreference = "Stop"
$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$EnvFile = Join-Path $RootDir ".env"
$KeyringFile = Join-Path $RootDir ".secrets/keyring.json"
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $RootDir ".backups"
}

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

function Select-CapturedLine {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Text,
        [Parameter(Mandatory = $true)]
        [string]$Pattern,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

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

function Set-PrivateAcl([string]$Path, [bool]$IsDirectory) {
    if (-not (Get-Command icacls -ErrorAction SilentlyContinue)) { return }
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $rights = if ($IsDirectory) { "(OI)(CI)F" } else { "F" }
    & icacls $Path /inheritance:r /grant:r `
        "$identity`:$rights" `
        "*S-1-5-18`:$rights" `
        "*S-1-5-32-544`:$rights" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Não foi possível restringir a ACL do bundle."
    }
}

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLowerInvariant()
}

function Get-FileDescriptor([string]$Path) {
    $item = Get-Item -LiteralPath $Path
    return [ordered]@{
        sha256 = Get-Sha256 $Path
        size_bytes = [int64]$item.Length
    }
}

if (-not $AcknowledgeSensitive) {
    throw "Confirme o tratamento do bundle sensível com -AcknowledgeSensitive."
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker não encontrado."
}
Invoke-Docker -Arguments @("compose", "version") -Quiet
if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
    throw ".env não encontrado. Inicialize o ambiente comum antes do backup."
}
if (-not (Test-Path -LiteralPath $KeyringFile -PathType Leaf)) {
    throw "Keyring não encontrado. Inicialize o ambiente comum antes do backup."
}

$timestamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$backupId = "meufinanceiro-$timestamp-$(New-RandomHex 4)"
$backupRoot = [System.IO.Path]::GetFullPath($OutputDirectory)
$finalDir = Join-Path $backupRoot $backupId
$tempDir = Join-Path $backupRoot ".$backupId.tmp"
$containerDump = "/tmp/$backupId.dump"
$postgresContainer = ""
$published = $false

if (-not (Test-Path -LiteralPath $backupRoot)) {
    New-Item -ItemType Directory -Path $backupRoot | Out-Null
    Set-PrivateAcl -Path $backupRoot -IsDirectory $true
}
elseif (-not (Test-Path -LiteralPath $backupRoot -PathType Container)) {
    throw "O destino de backup não é um diretório."
}
if ((Test-Path -LiteralPath $finalDir) -or (Test-Path -LiteralPath $tempDir)) {
    throw "Já existe um bundle com o identificador gerado."
}

Push-Location $RootDir
try {
    $postgresOutput = Invoke-Docker -Arguments @("compose", "ps", "-q", "postgres") -Capture
    $postgresContainer = Select-CapturedLine `
        -Text $postgresOutput `
        -Pattern '^[0-9a-f]{12,64}$' `
        -Description "container PostgreSQL"

    $healthOutput = Invoke-Docker -Arguments @(
        "inspect",
        "--format",
        "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
        $postgresContainer
    ) -Capture
    $health = Select-CapturedLine `
        -Text $healthOutput `
        -Pattern '^(healthy|unhealthy|starting|running|exited)$' `
        -Description "health do PostgreSQL"
    if ($health -ne "healthy") {
        throw "PostgreSQL não está saudável; backup recusado."
    }

    $envHashBefore = Get-Sha256 $EnvFile
    $keyringHashBefore = Get-Sha256 $KeyringFile

    New-Item -ItemType Directory -Path $tempDir | Out-Null
    Set-PrivateAcl -Path $tempDir -IsDirectory $true
    $envCopy = Join-Path $tempDir "installation.env"
    $keyringCopy = Join-Path $tempDir "keyring.json"
    $dumpCopy = Join-Path $tempDir "database.dump"
    Copy-Item -LiteralPath $EnvFile -Destination $envCopy
    Copy-Item -LiteralPath $KeyringFile -Destination $keyringCopy
    Set-PrivateAcl -Path $envCopy -IsDirectory $false
    Set-PrivateAcl -Path $keyringCopy -IsDirectory $false

    $dumpCommand = 'umask 077; pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --format=custom --no-owner --no-privileges --file "$1"'
    Invoke-Docker -Arguments @(
        "compose", "exec", "-T", "postgres", "sh", "-ceu", $dumpCommand, "--", $containerDump
    ) -Quiet
    Invoke-Docker -Arguments @("cp", "$postgresContainer`:$containerDump", $dumpCopy) -Quiet
    Invoke-Docker -Arguments @("compose", "exec", "-T", "postgres", "rm", "-f", $containerDump) -Quiet
    Set-PrivateAcl -Path $dumpCopy -IsDirectory $false

    $revisionCommand = 'psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --tuples-only --no-align --command "SELECT version_num FROM alembic_version;"'
    $revisionOutput = Invoke-Docker -Arguments @(
        "compose", "exec", "-T", "postgres", "sh", "-ceu", $revisionCommand
    ) -Capture
    $schemaRevision = Select-CapturedLine `
        -Text $revisionOutput `
        -Pattern '^[0-9A-Za-z_]+$' `
        -Description "revisão Alembic"

    if ((Get-Sha256 $EnvFile) -ne $envHashBefore) {
        throw ".env mudou durante o backup; bundle descartado."
    }
    if ((Get-Sha256 $KeyringFile) -ne $keyringHashBefore) {
        throw "Keyring mudou durante o backup; bundle descartado."
    }
    if ((Get-Sha256 $envCopy) -ne $envHashBefore) {
        throw "Cópia de .env inconsistente; bundle descartado."
    }
    if ((Get-Sha256 $keyringCopy) -ne $keyringHashBefore) {
        throw "Cópia do keyring inconsistente; bundle descartado."
    }

    $databaseName = "meufinanceiro"
    Get-Content -LiteralPath $EnvFile | ForEach-Object {
        if ($_ -match '^POSTGRES_DB=(.+)$') { $databaseName = $Matches[1] }
    }

    $keyring = Get-Content -LiteralPath $keyringCopy -Raw | ConvertFrom-Json
    if ($keyring.version -ne 1 -or [string]::IsNullOrWhiteSpace($keyring.active_key_id)) {
        throw "Estrutura do keyring inválida."
    }
    $keyProperties = @($keyring.keys.PSObject.Properties)
    if ($keyProperties.Count -eq 0 -or -not ($keyProperties.Name -contains $keyring.active_key_id)) {
        throw "Chave ativa não existe no keyring."
    }

    $manifest = [ordered]@{
        format = "meufinanceiro-foundation-backup"
        version = 1
        backup_id = $backupId
        created_at = [DateTimeOffset]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
        sensitive = $true
        database = [ordered]@{
            name = $databaseName
            schema_revision = $schemaRevision
            dump_format = "postgresql-custom"
            postgres_image = "postgres:18.4-alpine"
        }
        keyring = [ordered]@{
            version = [int]$keyring.version
            active_key_id = [string]$keyring.active_key_id
            key_count = $keyProperties.Count
        }
        files = [ordered]@{
            "database.dump" = (Get-FileDescriptor $dumpCopy)
            "installation.env" = (Get-FileDescriptor $envCopy)
            "keyring.json" = (Get-FileDescriptor $keyringCopy)
        }
    }
    $manifestPath = Join-Path $tempDir "manifest.json"
    $manifestJson = $manifest | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText(
        $manifestPath,
        "$manifestJson`n",
        (New-Object System.Text.UTF8Encoding($false))
    )
    Set-PrivateAcl -Path $manifestPath -IsDirectory $false

    foreach ($fileName in @("database.dump", "installation.env", "keyring.json")) {
        $path = Join-Path $tempDir $fileName
        $expected = $manifest.files[$fileName]["sha256"]
        if ((Get-Sha256 $path) -ne $expected) {
            throw "Falha de integridade ao publicar $fileName."
        }
    }

    Move-Item -LiteralPath $tempDir -Destination $finalDir
    $published = $true
}
finally {
    if (-not [string]::IsNullOrWhiteSpace($postgresContainer)) {
        try {
            Invoke-Docker -Arguments @("compose", "exec", "-T", "postgres", "rm", "-f", $containerDump) -Quiet
        }
        catch { }
    }
    Pop-Location
    if (-not $published -and (Test-Path -LiteralPath $tempDir)) {
        Remove-Item -LiteralPath $tempDir -Recurse -Force
    }
}

Write-Warning "O bundle contém senhas e chave mestra; mova-o para armazenamento criptografado."
Write-Output $finalDir
