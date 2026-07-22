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

function Invoke-DemoCompose([string[]]$Arguments) {
    & docker compose `
        --project-name $ProjectName `
        --env-file $EnvFile `
        --profile demo `
        @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose falhou com exit code $LASTEXITCODE."
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker não encontrado."
}
docker compose version | Out-Null

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
"@
    [System.IO.File]::WriteAllText(
        $EnvFile,
        $envContent,
        (New-Object System.Text.UTF8Encoding($false))
    )
}
Set-PrivateAcl -Path $EnvFile -IsDirectory $false

$EnvContent = Get-Content $EnvFile
if ($EnvContent -notcontains "APP_DEMO_MODE=true") {
    throw "A configuração demo existente não possui APP_DEMO_MODE=true."
}
if ($EnvContent -notcontains "POSTGRES_DB=meufinanceiro_demo") {
    throw "A configuração demo existente usa um banco inesperado."
}

if (-not (Test-Path $KeyringFile)) {
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
}
Set-PrivateAcl -Path $KeyringFile -IsDirectory $false

Push-Location $RootDir
try {
    switch ($Action) {
        "up" {
            Invoke-DemoCompose @("up", "--build", "--detach", "--wait", "--wait-timeout", "180")
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
        }
        { $_ -in @("load", "status", "reset") } {
            Invoke-DemoCompose @(
                "run", "--rm", "demo-fixture",
                "python", "-m", "meufinanceiro_persistence.demo_cli", $Action
            )
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
