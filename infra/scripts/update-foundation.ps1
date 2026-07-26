[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetRef,
    [string]$BackupDirectory,
    [string]$RootDirectory,
    [switch]$AcknowledgeSensitive,
    [switch]$NoFetch,
    [switch]$AllowDetached,
    [switch]$SkipCheckoutAdvance
)

$ErrorActionPreference = "Stop"

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
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
            & $Command @Arguments 1> $stdoutPath 2> $stderrPath
            $exitCode = $LASTEXITCODE
            $stdoutText = [string](Get-Content -LiteralPath $stdoutPath -Raw -ErrorAction SilentlyContinue)
            $stderrText = [string](Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue)
        }
        else {
            $output = @(& $Command @Arguments 2>&1 | ForEach-Object { "$_" })
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
        $message = ([string]$stderrText).Trim()
        if (-not [string]::IsNullOrWhiteSpace($message)) { Write-Warning $message }
        throw "$Command falhou com código $exitCode."
    }
    if ($Capture) { return ([string]$stdoutText).Trim() }
    if (-not $Quiet) { $output | ForEach-Object { Write-Host $_ } }
}

function New-RandomHex([int]$ByteLength) {
    $bytes = New-Object byte[] $ByteLength
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) }
    finally { $rng.Dispose() }
    return -join ($bytes | ForEach-Object { $_.ToString("x2") })
}

function Get-EnvValue([string]$Path, [string]$Name) {
    $value = ""
    Get-Content -LiteralPath $Path | ForEach-Object {
        if ($_ -match "^$([regex]::Escape($Name))=(.*)$") { $value = $Matches[1] }
    }
    return $value
}

function Get-Hash([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Get-VolumeFingerprint([string]$ProjectDirectory) {
    $containerId = Invoke-Compose $ProjectDirectory @("ps", "-q", "postgres") -Capture
    if ([string]::IsNullOrWhiteSpace($containerId)) {
        throw "Container PostgreSQL da instalação não encontrado."
    }

    $containerJson = Invoke-Native -Command "docker" -Arguments @(
        "inspect", $containerId
    ) -Capture
    $containers = @($containerJson | ConvertFrom-Json)
    if ($containers.Count -ne 1) {
        throw "Inspeção do container PostgreSQL retornou resultado inválido."
    }
    $volumeMounts = @(
        $containers[0].Mounts |
            Where-Object {
                $_.Destination -eq "/var/lib/postgresql" -and
                -not [string]::IsNullOrWhiteSpace([string]$_.Name)
            }
    )
    if ($volumeMounts.Count -ne 1) {
        throw "Volume PostgreSQL da instalação não encontrado."
    }
    $volumeName = [string]$volumeMounts[0].Name

    $volumeJson = Invoke-Native -Command "docker" -Arguments @(
        "volume", "inspect", $volumeName
    ) -Capture
    $volumes = @($volumeJson | ConvertFrom-Json)
    if ($volumes.Count -ne 1) {
        throw "Inspeção do volume PostgreSQL retornou resultado inválido."
    }
    $volume = $volumes[0]
    $description = "$([string]$volume.Name)|$([string]$volume.Mountpoint)|$([string]$volume.CreatedAt)"
    $bytes = [Text.Encoding]::UTF8.GetBytes($description)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return -join ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") })
    }
    finally { $sha.Dispose() }
}

if (-not $AcknowledgeSensitive) {
    throw "Use -AcknowledgeSensitive para confirmar o conteúdo sensível do backup."
}

$defaultRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$RootDir = if ($RootDirectory) { (Resolve-Path $RootDirectory).Path } else { $defaultRoot }
$EnvFile = Join-Path $RootDir ".env"
$KeyringFile = Join-Path $RootDir ".secrets/keyring.json"
$UpdatesDir = Join-Path $RootDir ".updates"
$BackupRoot = if ($BackupDirectory) { $BackupDirectory } else { Join-Path $RootDir ".backups" }
$UpdateId = "update-$([DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssZ'))-$(New-RandomHex 4)"
$StateDir = Join-Path $UpdatesDir $UpdateId
$StateFile = Join-Path $StateDir "state.json"
$LockDir = Join-Path $UpdatesDir "update.lock"
$TargetWorktree = Join-Path ([System.IO.Path]::GetTempPath()) "meufinanceiro-$UpdateId"
$SourceCommit = ""
$TargetCommit = ""
$SourceSchema = ""
$CurrentSchema = ""
$BackupId = ""
$VolumeFingerprint = ""
$LockHeld = $false
$WorktreeAdded = $false

New-Item -ItemType Directory -Path $StateDir -Force | Out-Null

function Write-State([string]$Status, [string]$Detail) {
    $payload = [ordered]@{
        format = "meufinanceiro-foundation-update"
        version = 1
        update_id = $UpdateId
        status = $Status
        updated_at = [DateTimeOffset]::UtcNow.ToString("o")
        source_commit = if ($SourceCommit) { $SourceCommit } else { $null }
        target_commit = if ($TargetCommit) { $TargetCommit } else { $null }
        source_schema_revision = if ($SourceSchema) { $SourceSchema } else { $null }
        current_schema_revision = if ($CurrentSchema) { $CurrentSchema } else { $null }
        backup_id = if ($BackupId) { $BackupId } else { $null }
        volume_fingerprint_sha256 = if ($VolumeFingerprint) { $VolumeFingerprint } else { $null }
        detail = if ($Detail) { $Detail } else { $null }
    }
    $temporary = "$StateFile.tmp-$PID"
    $json = $payload | ConvertTo-Json -Depth 4
    [System.IO.File]::WriteAllText(
        $temporary,
        "$json`n",
        (New-Object System.Text.UTF8Encoding($false))
    )
    Move-Item -LiteralPath $temporary -Destination $StateFile -Force
}

function Invoke-Git([string[]]$Arguments, [switch]$Capture, [switch]$Quiet) {
    return Invoke-Native -Command "git" -Arguments (@("-C", $RootDir) + $Arguments) -Capture:$Capture -Quiet:$Quiet
}

function Invoke-Compose([string]$ProjectDirectory, [string[]]$Arguments, [switch]$Capture, [switch]$Quiet) {
    $previousKeyring = $env:APP_KEYRING_FILE_HOST
    try {
        $env:APP_KEYRING_FILE_HOST = $KeyringFile
        $composeArgs = @(
            "compose", "--project-directory", $ProjectDirectory,
            "--env-file", $EnvFile, "-f", (Join-Path $ProjectDirectory "compose.yaml")
        ) + $Arguments
        return Invoke-Native -Command "docker" -Arguments $composeArgs -Capture:$Capture -Quiet:$Quiet
    }
    finally { $env:APP_KEYRING_FILE_HOST = $previousKeyring }
}

function Get-SchemaRevision([string]$ProjectDirectory) {
    $postgresUser = Get-EnvValue $EnvFile "POSTGRES_USER"
    $postgresDb = Get-EnvValue $EnvFile "POSTGRES_DB"
    $output = Invoke-Compose $ProjectDirectory @(
        "exec", "-T", "postgres", "psql",
        "--username", $postgresUser,
        "--dbname", $postgresDb,
        "--tuples-only", "--no-align",
        "--command", "SELECT version_num FROM alembic_version;"
    ) -Capture
    return ($output -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ })[-1]
}

function Invoke-Smoke([string]$ProjectDirectory) {
    $port = Get-EnvValue $EnvFile "APP_HTTP_PORT"
    if ([string]::IsNullOrWhiteSpace($port)) { $port = "8080" }
    $baseUrl = "http://127.0.0.1:$port"
    $healthy = $false
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        try {
            $api = Invoke-WebRequest -UseBasicParsing "$baseUrl/api/v1/health/ready"
            $web = Invoke-WebRequest -UseBasicParsing "$baseUrl/"
            $bootstrap = Invoke-WebRequest -UseBasicParsing "$baseUrl/app_bootstrap.js"
            Invoke-Compose $ProjectDirectory @(
                "exec", "-T", "worker", "python", "-c",
                "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health/ready', timeout=2)"
            ) -Quiet
            if (
                $api.StatusCode -eq 200 -and $web.StatusCode -eq 200 -and
                $web.Content -match "app_bootstrap\.js" -and
                $bootstrap.Content -match "register\('sw\.js'" -and
                $bootstrap.Content -match "flutter_bootstrap\.js"
            ) { $healthy = $true; break }
        }
        catch { Start-Sleep -Seconds 2 }
    }
    if (-not $healthy) { throw "Smoke HTTP/Worker falhou." }

    $idempotencyKey = "update-$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())-$PID"
    $first = Invoke-Compose $ProjectDirectory @(
        "exec", "-T", "api", "python", "-m", "meufinanceiro_persistence.cli",
        "enqueue-demo", "--idempotency-key", $idempotencyKey
    ) -Capture | ConvertFrom-Json
    $second = Invoke-Compose $ProjectDirectory @(
        "exec", "-T", "api", "python", "-m", "meufinanceiro_persistence.cli",
        "enqueue-demo", "--idempotency-key", $idempotencyKey
    ) -Capture | ConvertFrom-Json
    if ($first.id -ne $second.id) { throw "Idempotência retornou tarefas diferentes." }
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        $task = Invoke-Compose $ProjectDirectory @(
            "exec", "-T", "api", "python", "-m", "meufinanceiro_persistence.cli",
            "get", "--task-id", $first.id
        ) -Capture | ConvertFrom-Json
        if ($task.status -eq "succeeded") { return }
        Start-Sleep -Seconds 1
    }
    throw "Worker não concluiu a tarefa de smoke."
}

function Invoke-ControlledRollback {
    try { $script:CurrentSchema = Get-SchemaRevision $TargetWorktree }
    catch { $script:CurrentSchema = "" }
    if ($env:MEUFINANCEIRO_UPDATE_TEST_SCHEMA_OVERRIDE_AFTER_FAILURE) {
        $script:CurrentSchema = $env:MEUFINANCEIRO_UPDATE_TEST_SCHEMA_OVERRIDE_AFTER_FAILURE
    }

    if ($CurrentSchema -and $CurrentSchema -eq $SourceSchema) {
        try {
            Invoke-Compose $RootDir @("up", "--build", "--detach", "--wait", "--wait-timeout", "180")
            Invoke-Smoke $RootDir
            if ((Get-Hash $EnvFile) -ne $script:EnvHash) { throw ".env alterado." }
            if ((Get-Hash $KeyringFile) -ne $script:KeyringHash) { throw "Keyring alterado." }
            if ((Get-VolumeFingerprint $RootDir) -ne $VolumeFingerprint) { throw "Volume PostgreSQL alterado." }
            Write-State "ROLLED_BACK" "target_failed_schema_unchanged"
            $rollbackError = [System.Exception]::new(
                "A atualização falhou e o commit anterior foi restaurado com schema inalterado."
            )
            $rollbackError.Data["UpdateExitCode"] = 2
            throw $rollbackError
        }
        catch {
            if ($_.Exception.Data["UpdateExitCode"] -eq 2) { throw }
        }
    }

    try { Invoke-Compose $TargetWorktree @("stop", "caddy", "api", "worker", "web") -Quiet }
    catch { }
    Write-State "ROLLBACK_REQUIRES_COORDINATED_RESTORE" "schema_changed_or_unknown"
    $restoreError = [System.Exception]::new(
        "Rollback automático bloqueado. Preserve o bundle $BackupId para recuperação coordenada."
    )
    $restoreError.Data["UpdateExitCode"] = 3
    throw $restoreError
}

$FinalError = $null
$FinalExitCode = 0
try {
    foreach ($commandName in @("git", "docker")) {
        if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
            Write-State "FAILED_PRECHECK" "missing_$commandName"
            throw "$commandName não encontrado."
        }
    }
    Invoke-Native -Command "docker" -Arguments @("compose", "version") -Quiet

    try { New-Item -ItemType Directory -Path $LockDir -ErrorAction Stop | Out-Null }
    catch { Write-State "FAILED_PRECHECK" "update_lock_busy"; throw "Outra atualização está em andamento." }
    $LockHeld = $true

    foreach ($required in @($EnvFile, $KeyringFile, (Join-Path $RootDir "compose.yaml"))) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            Write-State "FAILED_PRECHECK" "required_file_missing"
            throw "Arquivo obrigatório ausente."
        }
    }

    $tracked = Invoke-Git @("status", "--porcelain", "--untracked-files=no") -Capture
    if (-not [string]::IsNullOrWhiteSpace($tracked)) {
        Write-State "FAILED_PRECHECK" "tracked_changes"
        throw "O checkout possui alterações rastreadas."
    }
    $branch = ""
    try { $branch = Invoke-Git @("symbolic-ref", "--quiet", "--short", "HEAD") -Capture }
    catch { }
    if (-not $AllowDetached -and $branch -ne "develop") {
        Write-State "FAILED_PRECHECK" "branch_not_develop"
        throw "A atualização comum deve ser executada na branch develop."
    }

    $SourceCommit = Invoke-Git @("rev-parse", "HEAD") -Capture
    if (-not $NoFetch) {
        try { Invoke-Git @("fetch", "--prune", "origin", "develop") -Quiet }
        catch { Write-State "FAILED_PRECHECK" "git_fetch_failed"; throw }
    }
    try { $TargetCommit = Invoke-Git @("rev-parse", "$TargetRef^{commit}") -Capture }
    catch { Write-State "FAILED_PRECHECK" "target_unresolved"; throw }
    try { Invoke-Git @("merge-base", "--is-ancestor", $SourceCommit, $TargetCommit) -Quiet }
    catch {
        Write-State "FAILED_PRECHECK" "target_not_fast_forward"
        throw "O target não é descendente fast-forward do commit atual."
    }

    $script:EnvHash = Get-Hash $EnvFile
    $script:KeyringHash = Get-Hash $KeyringFile
    try { $VolumeFingerprint = Get-VolumeFingerprint $RootDir }
    catch { Write-State "FAILED_PRECHECK" "volume_missing"; throw }

    try { $SourceSchema = Get-SchemaRevision $RootDir }
    catch { Write-State "FAILED_PRECHECK" "schema_revision_missing"; throw }
    if ([string]::IsNullOrWhiteSpace($SourceSchema)) {
        Write-State "FAILED_PRECHECK" "schema_revision_missing"
        throw "Revisão Alembic atual não encontrada."
    }
    $CurrentSchema = $SourceSchema
    if ($SourceCommit -eq $TargetCommit) {
        Write-State "APPLIED" "target_already_applied"
        Write-Output $StateFile
        return
    }

    $backupCreate = Join-Path $RootDir "infra/scripts/backup-create.ps1"
    $backupVerify = Join-Path $RootDir "infra/scripts/backup-verify.ps1"
    try {
        $bundleOutput = @(& $backupCreate -AcknowledgeSensitive -OutputDirectory $BackupRoot)
        $bundlePath = [string]($bundleOutput | Select-Object -Last 1)
        if ([string]::IsNullOrWhiteSpace($bundlePath)) { throw "Caminho do backup ausente." }
    }
    catch { Write-State "FAILED_PRECHECK" "backup_create_failed"; throw }
    try { & $backupVerify $bundlePath }
    catch { Write-State "FAILED_PRECHECK" "backup_verify_failed"; throw }
    $BackupId = Split-Path -Leaf $bundlePath
    Write-State "PREPARED" "backup_verified"

    Invoke-Git @("worktree", "add", "--detach", $TargetWorktree, $TargetCommit) -Quiet
    $WorktreeAdded = $true

    try { Invoke-Compose $TargetWorktree @("build") }
    catch { Write-State "FAILED_PRECHECK" "target_build_failed"; throw }

    try {
        Invoke-Compose $TargetWorktree @("up", "--detach", "--wait", "--wait-timeout", "180")
        if ($env:MEUFINANCEIRO_UPDATE_TEST_FAIL_AFTER_START -eq "1") {
            throw "Falha de teste injetada após startup."
        }
        Invoke-Smoke $TargetWorktree
        $CurrentSchema = Get-SchemaRevision $TargetWorktree
        if ((Get-Hash $EnvFile) -ne $EnvHash) { throw ".env alterado durante a atualização." }
        if ((Get-Hash $KeyringFile) -ne $KeyringHash) { throw "Keyring alterado durante a atualização." }
        if ((Get-VolumeFingerprint $TargetWorktree) -ne $VolumeFingerprint) { throw "Volume PostgreSQL alterado durante a atualização." }
    }
    catch { Invoke-ControlledRollback }

    if (-not $SkipCheckoutAdvance) {
        try { Invoke-Git @("merge", "--ff-only", $TargetCommit) }
        catch { Invoke-ControlledRollback }
    }
    Write-State "APPLIED" "target_started_and_smoke_passed"
    Write-Output $StateFile
}
catch {
    $FinalError = $_
    if ($_.Exception.Data["UpdateExitCode"]) {
        $FinalExitCode = [int]$_.Exception.Data["UpdateExitCode"]
    }
    else { $FinalExitCode = 1 }
}
finally {
    if ($WorktreeAdded) {
        try { Invoke-Git @("worktree", "remove", "--force", $TargetWorktree) -Quiet }
        catch { }
    }
    Remove-Item -LiteralPath $TargetWorktree -Recurse -Force -ErrorAction SilentlyContinue
    if ($LockHeld) { Remove-Item -LiteralPath $LockDir -Force -ErrorAction SilentlyContinue }
}
if ($FinalError) {
    [Console]::Error.WriteLine($FinalError.Exception.Message)
    exit $FinalExitCode
}
