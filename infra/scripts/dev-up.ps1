$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$EnvFile = Join-Path $RootDir ".env"
$SecretsDir = Join-Path $RootDir ".secrets"
$KeyringFile = Join-Path $SecretsDir "keyring.json"

function New-RandomBytes([int]$Length) {
    $bytes = New-Object byte[] $Length
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    return $bytes
}

function ConvertTo-Base64Url([byte[]]$Bytes) {
    return [Convert]::ToBase64String($Bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker não encontrado."
}

docker compose version | Out-Null

if (-not (Test-Path $EnvFile)) {
    $password = -join ((New-RandomBytes 24) | ForEach-Object { $_.ToString("x2") })

    @"
POSTGRES_DB=meufinanceiro
POSTGRES_USER=meufinanceiro
POSTGRES_PASSWORD=$password
APP_HTTP_PORT=8080
APP_KEYRING_FILE_HOST=.secrets/keyring.json
"@ | Set-Content -Path $EnvFile -Encoding utf8

    Write-Host "Configuração local criada em .env."
}
elseif (-not (Select-String -Path $EnvFile -Pattern '^APP_KEYRING_FILE_HOST=' -Quiet)) {
    Add-Content -Path $EnvFile -Value "`nAPP_KEYRING_FILE_HOST=.secrets/keyring.json"
}

if (-not (Test-Path $KeyringFile)) {
    New-Item -ItemType Directory -Path $SecretsDir -Force | Out-Null
    $keyId = "k_$(ConvertTo-Base64Url (New-RandomBytes 12))"
    $keys = [ordered]@{}
    $keys[$keyId] = ConvertTo-Base64Url (New-RandomBytes 32)
    $keyring = [ordered]@{
        active_key_id = $keyId
        keys = $keys
        version = 1
    }
    $json = $keyring | ConvertTo-Json -Compress -Depth 4
    [System.IO.File]::WriteAllText(
        $KeyringFile,
        "$json`n",
        (New-Object System.Text.UTF8Encoding($false))
    )

    if (Get-Command icacls -ErrorAction SilentlyContinue) {
        & icacls $SecretsDir /inheritance:r /grant:r "$env:USERNAME`:(OI)(CI)F" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Não foi possível restringir automaticamente a ACL de .secrets."
        }
    }
    Write-Host "Keyring local criado em .secrets/keyring.json."
}

$port = 8080
Get-Content $EnvFile | ForEach-Object {
    if ($_ -match '^APP_HTTP_PORT=(\d+)$') {
        $port = [int]$Matches[1]
    }
}

Push-Location $RootDir
try {
    docker compose up --build --detach

    $baseUrl = "http://127.0.0.1:$port"
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        try {
            $api = Invoke-WebRequest -UseBasicParsing "$baseUrl/api/v1/health/ready"
            $web = Invoke-WebRequest -UseBasicParsing "$baseUrl/"
            if ($api.StatusCode -eq 200 -and $web.StatusCode -eq 200) {
                Write-Host "MeuFinanceiro disponível em $baseUrl"
                exit 0
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }

    throw "Smoke test falhou após 60 tentativas."
}
finally {
    Pop-Location
}
