[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8080"
)

$ErrorActionPreference = "Stop"
$RootDirectory = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$Failures = 0
$Warnings = 0

function Write-Ok([string]$Message) {
    Write-Output "OK   $Message"
}

function Write-DoctorWarning([string]$Message) {
    $script:Warnings++
    Write-Output "WARN $Message"
}

function Write-Fail([string]$Message) {
    $script:Failures++
    [Console]::Error.WriteLine("FAIL $Message")
}

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
        $stdoutText = [string](Get-Content -LiteralPath $stdoutPath -Raw -ErrorAction SilentlyContinue)
        $stderrText = [string](Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue)
        return [pscustomobject]@{
            ExitCode = $exitCode
            Stdout = ([string]$stdoutText).Trim()
            Stderr = ([string]$stderrText).Trim()
        }
    }
    finally {
        Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    }
}

Write-Output "MeuFinanceiro doctor (somente leitura)"
Write-Output "Raiz: <REPOSITORY>"
Write-Output "Endpoint: $BaseUrl"

$hasGit = $null -ne (Get-Command "git" -ErrorAction SilentlyContinue)
$hasDocker = $null -ne (Get-Command "docker" -ErrorAction SilentlyContinue)

if ($hasGit) { Write-Ok "git disponível" }
else { Write-Fail "git não encontrado" }

if ($hasDocker) { Write-Ok "docker disponível" }
else { Write-Fail "docker não encontrado" }

if ($hasGit) {
    $inside = Invoke-NativeCapture "git" @("-C", $RootDirectory, "rev-parse", "--is-inside-work-tree")
    if ($inside.ExitCode -eq 0) {
        Write-Ok "checkout Git válido"
        $branch = Invoke-NativeCapture "git" @("-C", $RootDirectory, "symbolic-ref", "--quiet", "--short", "HEAD")
        if ($branch.ExitCode -eq 0 -and $branch.Stdout -eq "develop") {
            Write-Ok "branch develop"
        }
        elseif ($branch.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($branch.Stdout)) {
            Write-DoctorWarning "branch atual é $($branch.Stdout); a instalação comum usa develop"
        }
        else {
            Write-DoctorWarning "checkout detached"
        }

        $tracked = Invoke-NativeCapture "git" @("-C", $RootDirectory, "status", "--porcelain", "--untracked-files=no")
        if ($tracked.ExitCode -eq 0 -and [string]::IsNullOrWhiteSpace($tracked.Stdout)) {
            Write-Ok "checkout sem alterações rastreadas"
        }
        else {
            Write-DoctorWarning "checkout possui alterações rastreadas"
        }
    }
    else {
        Write-Fail "a raiz não é um checkout Git"
    }
}

$composeFile = Join-Path $RootDirectory "compose.yaml"
$envFile = Join-Path $RootDirectory ".env"
$keyringFile = Join-Path $RootDirectory ".secrets/keyring.json"

if (Test-Path -LiteralPath $composeFile -PathType Leaf) {
    Write-Ok "compose.yaml presente"
}
else {
    Write-Fail "compose.yaml ausente"
}

if (Test-Path -LiteralPath $envFile -PathType Leaf) {
    Write-Ok ".env presente (conteúdo não lido)"
}
else {
    Write-DoctorWarning ".env ausente; a instalação comum ainda pode não ter sido inicializada"
}

if (Test-Path -LiteralPath $keyringFile -PathType Leaf) {
    Write-Ok "keyring presente (conteúdo não lido)"
}
else {
    Write-DoctorWarning "keyring ausente; a instalação comum ainda pode não ter sido inicializada"
}

if ($hasDocker) {
    $engine = Invoke-NativeCapture "docker" @("version")
    if ($engine.ExitCode -eq 0) {
        Write-Ok "Docker Engine acessível"
    }
    else {
        Write-Fail "Docker Engine indisponível"
    }

    $compose = Invoke-NativeCapture "docker" @("compose", "version")
    if ($compose.ExitCode -eq 0) {
        Write-Ok "Docker Compose v2 disponível"
    }
    else {
        Write-Fail "Docker Compose v2 não encontrado"
    }

    if ((Test-Path -LiteralPath $composeFile -PathType Leaf) -and (Test-Path -LiteralPath $envFile -PathType Leaf)) {
        $composePrefix = @(
            "compose", "--project-directory", $RootDirectory,
            "--env-file", $envFile, "-f", $composeFile
        )
        $contract = Invoke-NativeCapture "docker" ($composePrefix + @("config", "--services"))
        if ($contract.ExitCode -eq 0) {
            Write-Ok "contrato Compose resolvido"
        }
        else {
            Write-Fail "contrato Compose inválido ou configuração incompleta"
        }

        $running = Invoke-NativeCapture "docker" ($composePrefix + @("ps", "--status", "running", "-q"))
        if ($running.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($running.Stdout)) {
            Write-Ok "stack possui serviços em execução"
        }
        else {
            Write-DoctorWarning "nenhum serviço da stack está em execução"
        }
    }
}

try {
    $ready = Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/api/v1/health/ready" -TimeoutSec 4
    if ($ready.StatusCode -eq 200) {
        Write-Ok "API readiness saudável"
    }
    else {
        Write-DoctorWarning "API readiness respondeu HTTP $($ready.StatusCode)"
    }
}
catch {
    Write-DoctorWarning "API readiness indisponível em $BaseUrl"
}

Write-Output "SUMMARY failures=$Failures warnings=$Warnings"
if ($Failures -gt 0) { exit 1 }
exit 0
