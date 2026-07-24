$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$EnvFile = Join-Path $RootDir ".env"
$SecretsDir = Join-Path $RootDir ".secrets"
$KeyringFile = Join-Path $SecretsDir "keyring.json"

function Invoke-Docker {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [switch]$Capture,
        [switch]$Quiet
    )

    $previousPreference = $ErrorActionPreference
    $stderrPath = $null
    $stderrText = ""
    try {
        $ErrorActionPreference = "Continue"
        if ($Capture) {
            $stderrPath = [System.IO.Path]::GetTempFileName()
            $output = @(& docker @Arguments 2> $stderrPath | ForEach-Object { "$_" })
            $exitCode = $LASTEXITCODE
            if (Test-Path -LiteralPath $stderrPath) {
                $stderrText = [string](
                    Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue
                )
                $stderrText = $stderrText.Trim()
            }
        }
        else {
            $output = @(& docker @Arguments 2>&1 | ForEach-Object { "$_" })
            $exitCode = $LASTEXITCODE
        }
    }
    finally {
        $ErrorActionPreference = $previousPreference
        if ($stderrPath -and (Test-Path -LiteralPath $stderrPath)) {
            Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue
        }
    }

    if ($exitCode -ne 0) {
        if (-not [string]::IsNullOrWhiteSpace($stderrText)) {
            Write-Warning $stderrText
        }
        throw "Comando Docker falhou com código $exitCode."
    }
    if ($Capture) {
        return (($output -join "`n").Trim())
    }
    if (-not $Quiet) {
        $output | ForEach-Object { Write-Host $_ }
    }
}

function New-RandomBytes([int]$Length) {
    $bytes = New-Object byte[] $Length
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) }
    finally { $rng.Dispose() }
    return $bytes
}

function New-RandomPassword() {
    return -join ((New-RandomBytes 24) | ForEach-Object { $_.ToString("x2") })
}

function ConvertTo-Base64Url([byte[]]$Bytes) {
    return [Convert]::ToBase64String($Bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
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
        Write-Warning "Não foi possível restringir automaticamente a ACL de $Path."
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker não encontrado."
}
Invoke-Docker -Arguments @("compose", "version") -Quiet

if (-not (Test-Path $EnvFile)) {
    $adminPassword = New-RandomPassword
    $appPassword = New-RandomPassword
    @"
POSTGRES_DB=meufinanceiro
POSTGRES_USER=meufinanceiro_admin
POSTGRES_PASSWORD=$adminPassword
APP_DATABASE_USER=meufinanceiro_app
APP_DATABASE_PASSWORD=$appPassword
APP_HTTP_PORT=8080
APP_KEYRING_FILE_HOST=.secrets/keyring.json
"@ | Set-Content -Path $EnvFile -Encoding utf8
    Write-Host "Configuração local criada em .env."
}
else {
    if (-not (Select-String -Path $EnvFile -Pattern '^APP_DATABASE_USER=' -Quiet)) {
        Add-Content -Path $EnvFile -Value "`nAPP_DATABASE_USER=meufinanceiro_app"
    }
    if (-not (Select-String -Path $EnvFile -Pattern '^APP_DATABASE_PASSWORD=' -Quiet)) {
        Add-Content -Path $EnvFile -Value "APP_DATABASE_PASSWORD=$(New-RandomPassword)"
    }
    if (-not (Select-String -Path $EnvFile -Pattern '^APP_KEYRING_FILE_HOST=' -Quiet)) {
        Add-Content -Path $EnvFile -Value "APP_KEYRING_FILE_HOST=.secrets/keyring.json"
    }
}
Set-PrivateAcl -Path $EnvFile -IsDirectory $false

if (-not (Test-Path $KeyringFile)) {
    New-Item -ItemType Directory -Path $SecretsDir -Force | Out-Null
    $keyId = "k_$(ConvertTo-Base64Url (New-RandomBytes 12))"
    $keys = [ordered]@{}
    $keys[$keyId] = ConvertTo-Base64Url (New-RandomBytes 32)
    $keyring = [ordered]@{ active_key_id = $keyId; keys = $keys; version = 1 }
    $json = $keyring | ConvertTo-Json -Compress -Depth 4
    [System.IO.File]::WriteAllText(
        $KeyringFile,
        "$json`n",
        (New-Object System.Text.UTF8Encoding($false))
    )
    Write-Host "Keyring local criado em .secrets/keyring.json."
}
Set-PrivateAcl -Path $SecretsDir -IsDirectory $true
Set-PrivateAcl -Path $KeyringFile -IsDirectory $false

$port = 8080
Get-Content $EnvFile | ForEach-Object {
    if ($_ -match '^APP_HTTP_PORT=(\d+)$') { $port = [int]$Matches[1] }
}

Push-Location $RootDir
try {
    Invoke-Docker -Arguments @("compose", "up", "--build", "--detach", "--wait")

    $baseUrl = "http://127.0.0.1:$port"
    $healthy = $false
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        try {
            $api = Invoke-WebRequest -UseBasicParsing "$baseUrl/api/v1/health/ready"
            $web = Invoke-WebRequest -UseBasicParsing "$baseUrl/"
            $bootstrap = Invoke-WebRequest -UseBasicParsing "$baseUrl/app_bootstrap.js"
            Invoke-Docker -Arguments @(
                "compose", "exec", "-T", "worker", "python", "-c",
                "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health/ready', timeout=2)"
            ) -Quiet

            if (
                $api.StatusCode -eq 200 -and
                $web.StatusCode -eq 200 -and
                $web.Content -match 'app_bootstrap\.js' -and
                $bootstrap.StatusCode -eq 200 -and
                $bootstrap.Content -match "register\('sw\.js'" -and
                $bootstrap.Content -match "flutter_bootstrap\.js"
            ) {
                $healthy = $true
                break
            }
        }
        catch { Start-Sleep -Seconds 2 }
    }
    if (-not $healthy) {
        throw "Smoke test do Flutter Web falhou após 60 tentativas."
    }

    $idempotencyKey = "smoke-$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())-$PID"
    $first = (Invoke-Docker -Arguments @(
        "compose", "exec", "-T", "api", "python", "-m",
        "meufinanceiro_persistence.cli", "enqueue-demo", "--idempotency-key",
        $idempotencyKey
    ) -Capture | ConvertFrom-Json)
    $second = (Invoke-Docker -Arguments @(
        "compose", "exec", "-T", "api", "python", "-m",
        "meufinanceiro_persistence.cli", "enqueue-demo", "--idempotency-key",
        $idempotencyKey
    ) -Capture | ConvertFrom-Json)
    if ($first.id -ne $second.id) {
        throw "A verificação de idempotência retornou tarefas diferentes."
    }

    for ($attempt = 1; $attempt -le 60; $attempt++) {
        $task = (Invoke-Docker -Arguments @(
            "compose", "exec", "-T", "api", "python", "-m",
            "meufinanceiro_persistence.cli", "get", "--task-id", $first.id
        ) -Capture | ConvertFrom-Json)
        if ($task.status -eq "succeeded") {
            Write-Host "MeuFinanceiro Flutter disponível em $baseUrl"
            return
        }
        Start-Sleep -Seconds 1
    }
    throw "Worker não concluiu a tarefa de smoke test."
}
finally { Pop-Location }
