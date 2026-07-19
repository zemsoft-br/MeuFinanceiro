$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$EnvFile = Join-Path $RootDir ".env"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker não encontrado."
}

docker compose version | Out-Null

if (-not (Test-Path $EnvFile)) {
    $bytes = New-Object byte[] 24
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    $password = -join ($bytes | ForEach-Object { $_.ToString("x2") })

    @"
POSTGRES_DB=meufinanceiro
POSTGRES_USER=meufinanceiro
POSTGRES_PASSWORD=$password
APP_HTTP_PORT=8080
"@ | Set-Content -Path $EnvFile -Encoding utf8

    Write-Host "Configuração local criada em .env."
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
