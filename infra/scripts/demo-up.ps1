param(
    [ValidateSet("up", "load", "status", "reset", "down", "purge")]
    [string]$Action = "up"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$StateDir = Join-Path $RootDir ".demo"
$SecretsDir = Join-Path $StateDir "secrets"
$EnvFile = Join-Path $StateDir ".env"
$KeyringFile = Join-Path $SecretsDir "keyring.json"
$OperatorPasswordFile = Join-Path $SecretsDir "operator_password.txt"
$ProjectName = "meufinanceiro-demo"

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
        throw "Não foi possível restringir a ACL de $Path."
    }
}

function Write-Utf8NoBom([string]$Path, [string]$Content) {
    [System.IO.File]::WriteAllText(
        $Path,
        $Content,
        (New-Object System.Text.UTF8Encoding($false))
    )
}

function Invoke-DockerCompose([string[]]$Arguments) {
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & docker compose @Arguments 2>&1 | ForEach-Object { Write-Output $_ }
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) {
        throw "Docker Compose falhou com exit code $exitCode."
    }
}

function Invoke-BaseCompose([string[]]$Arguments) {
    Invoke-DockerCompose (@(
        "--project-name", $ProjectName,
        "--env-file", $EnvFile
    ) + $Arguments)
}

function Invoke-DemoCompose([string[]]$Arguments) {
    Invoke-DockerCompose (@(
        "--project-name", $ProjectName,
        "--env-file", $EnvFile,
        "--profile", "demo"
    ) + $Arguments)
}

function Invoke-FixtureCommand([string]$Command) {
    Invoke-DemoCompose @(
        "run", "--rm", "--no-deps", "demo-fixture",
        "python", "-m", "meufinanceiro_persistence.demo_cli", $Command
    )
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker não encontrado."
}
Invoke-DockerCompose @("version") | Out-Null

New-Item -ItemType Directory -Path $SecretsDir -Force | Out-Null
Set-PrivateAcl -Path $StateDir -IsDirectory $true
Set-PrivateAcl -Path $SecretsDir -IsDirectory $true

if (-not (Test-Path $EnvFile)) {
    $envContent = @"
POSTGRES_DB=meufinanceiro_demo
POSTGRES_USER=meufinanceiro_demo_admin
POSTGRES_PASSWORD=$(New-RandomPassword)
APP_DATABASE_USER=meufinanceiro_demo_app
APP_DATABASE_PASSWORD=$(New-RandomPassword)
APP_HTTP_PORT=8081
APP_DEMO_MODE=true
APP_KEYRING_FILE_HOST=.demo/secrets/keyring.json
DEMO_OPERATOR_PASSWORD_FILE_HOST=.demo/secrets/operator_password.txt
"@
    Write-Utf8NoBom -Path $EnvFile -Content $envContent
}
Set-PrivateAcl -Path $EnvFile -IsDirectory $false

$EnvContent = @(Get-Content $EnvFile)
if ($EnvContent -notcontains "APP_DEMO_MODE=true") {
    throw "A configuração demo existente não possui APP_DEMO_MODE=true."
}
if ($EnvContent -notcontains "POSTGRES_DB=meufinanceiro_demo") {
    throw "A configuração demo existente usa um banco inesperado."
}

$LegacyPasswordLine = @(
    $EnvContent | Where-Object { $_ -match '^DEMO_OPERATOR_PASSWORD=' }
) | Select-Object -First 1
if ($null -ne $LegacyPasswordLine) {
    $LegacyPassword = $LegacyPasswordLine.Substring("DEMO_OPERATOR_PASSWORD=".Length)
    if (-not (Test-Path $OperatorPasswordFile) -and -not [string]::IsNullOrEmpty($LegacyPassword)) {
        Write-Utf8NoBom -Path $OperatorPasswordFile -Content "$LegacyPassword`n"
        Set-PrivateAcl -Path $OperatorPasswordFile -IsDirectory $false
    }
    $EnvContent = @(
        $EnvContent | Where-Object { $_ -notmatch '^DEMO_OPERATOR_PASSWORD=' }
    )
    Write-Utf8NoBom -Path $EnvFile -Content (($EnvContent -join "`n") + "`n")
    Set-PrivateAcl -Path $EnvFile -IsDirectory $false
}

if (-not ($EnvContent | Where-Object { $_ -match '^DEMO_OPERATOR_PASSWORD_FILE_HOST=' })) {
    $EnvContent += "DEMO_OPERATOR_PASSWORD_FILE_HOST=.demo/secrets/operator_password.txt"
    Write-Utf8NoBom -Path $EnvFile -Content (($EnvContent -join "`n") + "`n")
    Set-PrivateAcl -Path $EnvFile -IsDirectory $false
}

if (-not (Test-Path $OperatorPasswordFile)) {
    Write-Utf8NoBom -Path $OperatorPasswordFile -Content "$(New-RandomPassword)`n"
}
Set-PrivateAcl -Path $OperatorPasswordFile -IsDirectory $false
$OperatorPassword = (Get-Content $OperatorPasswordFile -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($OperatorPassword)) {
    throw "A credencial privada do operador demo está vazia."
}

if (-not (Test-Path $KeyringFile)) {
    $keyId = "k_$(ConvertTo-Base64Url (New-RandomBytes 12))"
    $keys = [ordered]@{}
    $keys[$keyId] = ConvertTo-Base64Url (New-RandomBytes 32)
    $keyring = [ordered]@{ active_key_id = $keyId; keys = $keys; version = 1 }
    $json = $keyring | ConvertTo-Json -Compress -Depth 4
    Write-Utf8NoBom -Path $KeyringFile -Content "$json`n"
}
Set-PrivateAcl -Path $KeyringFile -IsDirectory $false

Push-Location $RootDir
try {
    switch ($Action) {
        "up" {
            Invoke-BaseCompose @("up", "--build", "--detach", "--wait", "--wait-timeout", "180")
            Invoke-FixtureCommand "load"
            $port = 8081
            $EnvContent | ForEach-Object {
                if ($_ -match '^APP_HTTP_PORT=(\d+)$') { $port = [int]$Matches[1] }
            }
            $loaded = $false
            for ($attempt = 1; $attempt -le 60; $attempt++) {
                try {
                    $status = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/v1/demo/status" -TimeoutSec 2
                    if ($status.enabled -eq $true -and $status.loaded -eq $true) {
                        $status | ConvertTo-Json -Compress
                        $loaded = $true
                        break
                    }
                }
                catch { Start-Sleep -Seconds 1 }
            }
            if (-not $loaded) {
                throw "O ambiente demo não confirmou fixture carregada."
            }
            Write-Host "MeuFinanceiro demo disponível em http://127.0.0.1:$port"
            Write-Host "Login demo: demo"
            Write-Host "Senha demo: $OperatorPassword"
        }
        { $_ -in @("load", "status", "reset") } {
            Invoke-FixtureCommand $Action
        }
        "down" {
            Invoke-DemoCompose @("down", "--remove-orphans", "--timeout", "40")
        }
        "purge" {
            Invoke-DemoCompose @("down", "--volumes", "--remove-orphans", "--timeout", "40")
            Remove-Item $StateDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
finally {
    Pop-Location
}
