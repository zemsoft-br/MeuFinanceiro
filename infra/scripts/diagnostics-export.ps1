[CmdletBinding()]
param(
    [string]$OutputDirectory,
    [string]$RootDirectory,
    [string]$BaseUrl = "http://127.0.0.1:8080"
)

$ErrorActionPreference = "Stop"
$DefaultRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$RootDir = if ($RootDirectory) { (Resolve-Path $RootDirectory).Path } else { $DefaultRoot }
$OutputRoot = if ($OutputDirectory) { $OutputDirectory } else { Join-Path $RootDir ".diagnostics" }
$EnvFile = Join-Path $RootDir ".env"
$KeyringFile = Join-Path $RootDir ".secrets/keyring.json"
$ComposeFile = Join-Path $RootDir "compose.yaml"
$Timestamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$RandomBytes = New-Object byte[] 4
$Random = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $Random.GetBytes($RandomBytes) }
finally { $Random.Dispose() }
$Suffix = -join ($RandomBytes | ForEach-Object { $_.ToString("x2") })
$BundleId = "meufinanceiro-diagnostics-$Timestamp-$Suffix"
$TemporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) "$BundleId-$PID"
$StagingDirectory = Join-Path $TemporaryRoot $BundleId
$ArchivePath = Join-Path $OutputRoot "$BundleId.zip"
$DoctorExit = 0

function Invoke-NativeCapture {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $stdoutPath = [System.IO.Path]::GetTempFileName()
    $stderrPath = [System.IO.Path]::GetTempFileName()
    try {
        & $Command @Arguments 1> $stdoutPath 2> $stderrPath
        $exitCode = $LASTEXITCODE
        $stdout = [System.IO.File]::ReadAllText($stdoutPath).Trim()
        $stderr = [System.IO.File]::ReadAllText($stderrPath).Trim()
        return [pscustomobject]@{
            ExitCode = $exitCode
            Stdout = $stdout
            Stderr = $stderr
        }
    }
    finally {
        Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    }
}

function Sanitize-Text([string]$Text) {
    $value = [string]$Text
    foreach ($entry in @(
        @($RootDir, "<REPOSITORY>"),
        @($HOME, "<HOME>")
    )) {
        if (-not [string]::IsNullOrWhiteSpace([string]$entry[0])) {
            $value = $value.Replace([string]$entry[0], [string]$entry[1])
            $value = $value.Replace(([string]$entry[0]).Replace("\", "/"), [string]$entry[1])
        }
    }

    $value = [regex]::Replace(
        $value,
        '(?i)(authorization\s*[:=]\s*bearer\s+)[A-Za-z0-9._~+/-]+=*',
        '$1[REDACTED]'
    )
    $value = [regex]::Replace(
        $value,
        '(?i)(postgres(?:ql)?://)([^@\s/]+)(@)',
        '$1[REDACTED]$3'
    )
    $value = [regex]::Replace(
        $value,
        '(?i)\b(POSTGRES_PASSWORD|APP_DATABASE_PASSWORD|DATABASE_URL|ACCESS_TOKEN|REFRESH_TOKEN|API_KEY|CLIENT_SECRET|PRIVATE_KEY)\b\s*[:=]\s*([^\s,;]+)',
        '$1=[REDACTED]'
    )
    $value = [regex]::Replace(
        $value,
        '(?i)"(password|database_url|access_token|refresh_token|client_secret|private_key)"\s*:\s*"[^"]*"',
        '"$1":"[REDACTED]"'
    )
    $value = [regex]::Replace(
        $value,
        '-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----',
        '[REDACTED_PRIVATE_KEY]',
        [Text.RegularExpressions.RegexOptions]::Singleline
    )
    $value = [regex]::Replace(
        $value,
        '\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b',
        '[REDACTED_JWT]'
    )
    return $value
}

function Write-SanitizedFile([string]$Path, [string]$Content) {
    [System.IO.File]::WriteAllText(
        $Path,
        "$(Sanitize-Text $Content)`n",
        (New-Object System.Text.UTF8Encoding($false))
    )
}

function Invoke-Compose([string[]]$Arguments) {
    $previousKeyring = $env:APP_KEYRING_FILE_HOST
    try {
        $env:APP_KEYRING_FILE_HOST = $KeyringFile
        $prefix = @(
            "compose", "--project-directory", $RootDir,
            "--env-file", $EnvFile, "-f", $ComposeFile
        )
        return Invoke-NativeCapture "docker" ($prefix + $Arguments)
    }
    finally {
        $env:APP_KEYRING_FILE_HOST = $previousKeyring
    }
}

try {
    foreach ($commandName in @("git", "docker")) {
        if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
            throw "$commandName não encontrado; não é possível gerar o bundle."
        }
    }
    if (-not (Get-Command "Compress-Archive" -ErrorAction SilentlyContinue)) {
        throw "Compress-Archive não encontrado."
    }

    New-Item -ItemType Directory -Path $StagingDirectory -Force | Out-Null
    New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

    Write-SanitizedFile (Join-Path $StagingDirectory "README.txt") @'
Bundle diagnóstico sanitizado do MeuFinanceiro.

Revise todos os arquivos antes de compartilhar. Este bundle não deve conter
.env, keyring, dumps, senhas, tokens, URLs de banco com credenciais ou chaves
privadas. Ele não substitui backup e não autoriza procedimentos destrutivos.
'@

    $gitVersion = Invoke-NativeCapture "git" @("--version")
    $dockerVersion = Invoke-NativeCapture "docker" @("--version")
    $composeVersion = Invoke-NativeCapture "docker" @("compose", "version")
    $serverVersion = Invoke-NativeCapture "docker" @("version")
    Write-SanitizedFile (Join-Path $StagingDirectory "versions.txt") @"
git=$($gitVersion.Stdout)
docker_client=$($dockerVersion.Stdout)
docker_compose=$($composeVersion.Stdout)
docker_engine_accessible=$($serverVersion.ExitCode -eq 0)
powershell=$($PSVersionTable.PSVersion)
"@

    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
    $drive = Get-PSDrive -Name ([System.IO.Path]::GetPathRoot($RootDir).TrimEnd('\').TrimEnd(':')) -ErrorAction SilentlyContinue
    $hostLines = @(
        "os_caption=$([string]$os.Caption)",
        "os_version=$([string]$os.Version)",
        "os_architecture=$([string]$os.OSArchitecture)",
        "process_architecture=$([System.Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture)",
        "drive_free_bytes=$([string]$drive.Free)",
        "drive_used_bytes=$([string]$drive.Used)"
    )
    Write-SanitizedFile (Join-Path $StagingDirectory "host.txt") ($hostLines -join "`n")

    $commit = Invoke-NativeCapture "git" @("-C", $RootDir, "rev-parse", "HEAD")
    $branch = Invoke-NativeCapture "git" @("-C", $RootDir, "symbolic-ref", "--quiet", "--short", "HEAD")
    $tracked = Invoke-NativeCapture "git" @("-C", $RootDir, "status", "--porcelain", "--untracked-files=no")
    Write-SanitizedFile (Join-Path $StagingDirectory "git.txt") @"
commit=$($commit.Stdout)
branch=$(if ($branch.ExitCode -eq 0) { $branch.Stdout } else { "detached" })
tracked_changes_begin
$($tracked.Stdout)
tracked_changes_end
"@

    $configLines = @(
        "env_present=$((Test-Path -LiteralPath $EnvFile -PathType Leaf).ToString().ToLowerInvariant())",
        "compose_present=$((Test-Path -LiteralPath $ComposeFile -PathType Leaf).ToString().ToLowerInvariant())",
        "keyring_present=$((Test-Path -LiteralPath $KeyringFile -PathType Leaf).ToString().ToLowerInvariant())"
    )
    if (Test-Path -LiteralPath $EnvFile -PathType Leaf) {
        $configLines += "env_sha256=$((Get-FileHash -Algorithm SHA256 -LiteralPath $EnvFile).Hash.ToLowerInvariant())"
    }
    if (Test-Path -LiteralPath $KeyringFile -PathType Leaf) {
        $configLines += "keyring_sha256=$((Get-FileHash -Algorithm SHA256 -LiteralPath $KeyringFile).Hash.ToLowerInvariant())"
    }
    Write-SanitizedFile (Join-Path $StagingDirectory "config-presence.txt") ($configLines -join "`n")

    $doctorPath = Join-Path $RootDir "infra/scripts/doctor.ps1"
    $doctorOutput = @(& $doctorPath -BaseUrl $BaseUrl 2>&1 | ForEach-Object { "$_" })
    $DoctorExit = $LASTEXITCODE
    Write-SanitizedFile (Join-Path $StagingDirectory "doctor.txt") (($doctorOutput + "doctor_exit_code=$DoctorExit") -join "`n")

    $composeAvailable = (
        $serverVersion.ExitCode -eq 0 -and
        $composeVersion.ExitCode -eq 0 -and
        (Test-Path -LiteralPath $ComposeFile -PathType Leaf) -and
        (Test-Path -LiteralPath $EnvFile -PathType Leaf)
    )

    if ($composeAvailable) {
        $composePs = Invoke-Compose @("ps", "--all", "--format", "json")
        $items = @()
        if ($composePs.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($composePs.Stdout)) {
            try {
                $items = @($composePs.Stdout | ConvertFrom-Json)
            }
            catch {
                foreach ($line in ($composePs.Stdout -split "`r?`n")) {
                    try { $items += ($line | ConvertFrom-Json) }
                    catch { }
                }
            }
        }
        $selected = @(
            foreach ($item in $items) {
                [ordered]@{
                    service = $item.Service
                    state = $item.State
                    health = $item.Health
                    exit_code = $item.ExitCode
                    image = $item.Image
                    publishers = @(
                        foreach ($publisher in @($item.Publishers)) {
                            [ordered]@{
                                protocol = $publisher.Protocol
                                target_port = $publisher.TargetPort
                                published_port = $publisher.PublishedPort
                                url = $publisher.URL
                            }
                        }
                    )
                }
            }
        )
        $composePsJson = if ($selected.Count -eq 0) {
            "[]"
        }
        else {
            $selected | ConvertTo-Json -Depth 6
        }
        Write-SanitizedFile (Join-Path $StagingDirectory "compose-ps.json") $composePsJson

        $logs = Invoke-Compose @(
            "logs", "--no-color", "--tail=200",
            "api", "worker", "migrate", "db-bootstrap", "postgres", "caddy", "web"
        )
        Write-SanitizedFile (Join-Path $StagingDirectory "logs.txt") ($logs.Stdout + "`n" + $logs.Stderr)

        $postgresUser = Invoke-Compose @("exec", "-T", "postgres", "printenv", "POSTGRES_USER")
        $postgresDb = Invoke-Compose @("exec", "-T", "postgres", "printenv", "POSTGRES_DB")
        $schema = if (
            $postgresUser.ExitCode -eq 0 -and
            $postgresDb.ExitCode -eq 0 -and
            -not [string]::IsNullOrWhiteSpace($postgresUser.Stdout) -and
            -not [string]::IsNullOrWhiteSpace($postgresDb.Stdout)
        ) {
            Invoke-Compose @(
                "exec", "-T", "postgres", "psql",
                "--username", $postgresUser.Stdout.Trim(),
                "--dbname", $postgresDb.Stdout.Trim(),
                "--tuples-only", "--no-align",
                "--command", "SELECT version_num FROM alembic_version;"
            )
        }
        else {
            [pscustomobject]@{
                ExitCode = 1
                Stdout = ""
                Stderr = "POSTGRES_USER ou POSTGRES_DB indisponível no container."
            }
        }
        $schemaValue = if ($schema.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($schema.Stdout)) {
            @($schema.Stdout -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })[-1].Trim()
        }
        else { "unavailable" }
        Write-SanitizedFile (Join-Path $StagingDirectory "schema-revision.txt") $schemaValue
    }
    else {
        Write-SanitizedFile (Join-Path $StagingDirectory "compose-ps.json") "[]"
        Write-SanitizedFile (Join-Path $StagingDirectory "logs.txt") "Stack indisponível; nenhum log coletado."
        Write-SanitizedFile (Join-Path $StagingDirectory "schema-revision.txt") "unavailable"
    }

    try {
        $health = Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/api/v1/health/ready" -TimeoutSec 5
        Write-SanitizedFile (Join-Path $StagingDirectory "health.json") $health.Content
    }
    catch {
        Write-SanitizedFile (Join-Path $StagingDirectory "health.json") '{"status":"unavailable"}'
    }

    $manifest = [ordered]@{
        format = "meufinanceiro-sanitized-diagnostics"
        version = 1
        bundle_id = $BundleId
        created_at_utc = $Timestamp
        doctor_exit_code = $DoctorExit
        files = @(
            Get-ChildItem -LiteralPath $StagingDirectory -File |
                Where-Object { $_.Name -ne "manifest.json" } |
                Sort-Object Name |
                ForEach-Object { $_.Name }
        )
        privacy = [ordered]@{
            contains_env = $false
            contains_keyring = $false
            contains_database_dump = $false
            automatic_upload = $false
        }
    }
    [System.IO.File]::WriteAllText(
        (Join-Path $StagingDirectory "manifest.json"),
        "$(ConvertTo-Json $manifest -Depth 5)`n",
        (New-Object System.Text.UTF8Encoding($false))
    )

    $forbiddenNames = @(
        ".env", "keyring.json", "database.dump", "installation.env"
    )
    $forbiddenExtensions = @(".dump", ".sql", ".pem", ".key", ".p12", ".pfx")
    $forbiddenFile = Get-ChildItem -LiteralPath $StagingDirectory -File -Recurse |
        Where-Object {
            $_.Name -in $forbiddenNames -or $_.Extension.ToLowerInvariant() -in $forbiddenExtensions
        } |
        Select-Object -First 1
    if ($forbiddenFile) { throw "Arquivo proibido detectado no bundle." }

    $contentPatterns = @(
        '-----BEGIN [A-Z ]*PRIVATE KEY-----',
        '(?i)postgres(?:ql)?://(?!\[REDACTED\]@)[^\s/]+@',
        '(?i)\b(?:POSTGRES_PASSWORD|APP_DATABASE_PASSWORD|DATABASE_URL|ACCESS_TOKEN|REFRESH_TOKEN|CLIENT_SECRET|PRIVATE_KEY)\b\s*[:=]\s*(?!\[REDACTED\])\S+',
        '\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b'
    )
    foreach ($file in Get-ChildItem -LiteralPath $StagingDirectory -File) {
        $text = [System.IO.File]::ReadAllText($file.FullName)
        foreach ($pattern in $contentPatterns) {
            if ([regex]::IsMatch($text, $pattern)) {
                throw "Conteúdo potencialmente sensível em $($file.Name)."
            }
        }
    }

    if (Test-Path -LiteralPath $ArchivePath) {
        Remove-Item -LiteralPath $ArchivePath -Force
    }
    Compress-Archive -Path (Join-Path $StagingDirectory "*") -DestinationPath $ArchivePath -CompressionLevel Optimal
    Write-Output $ArchivePath
}
finally {
    Remove-Item -LiteralPath $TemporaryRoot -Recurse -Force -ErrorAction SilentlyContinue
}
