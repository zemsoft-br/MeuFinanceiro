from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEV_UP = ROOT / "infra" / "scripts" / "dev-up.ps1"


def test_dev_up_wraps_docker_for_windows_powershell_51() -> None:
    content = DEV_UP.read_text(encoding="utf-8")

    assert '$ErrorActionPreference = "Stop"' in content
    assert "function Invoke-Docker" in content
    assert '$ErrorActionPreference = "Continue"' in content
    assert "$LASTEXITCODE" in content
    assert 'Invoke-Docker -Arguments @("compose", "up"' in content
    assert "docker compose up --build --detach --wait" not in content


def test_dev_up_is_composable_and_does_not_exit_the_host() -> None:
    content = DEV_UP.read_text(encoding="utf-8")

    assert "exit 0" not in content
    assert 'Write-Host "MeuFinanceiro Flutter disponível em $baseUrl"' in content
    assert "return" in content


def test_dev_up_captures_json_without_mixing_docker_stderr() -> None:
    content = DEV_UP.read_text(encoding="utf-8")

    assert "$stdoutPath = [System.IO.Path]::GetTempFileName()" in content
    assert "$stderrPath = [System.IO.Path]::GetTempFileName()" in content
    assert "1> $stdoutPath 2> $stderrPath" in content
    assert "Get-Content -LiteralPath $stdoutPath -Raw" in content
    assert "Get-Content -LiteralPath $stderrPath -Raw" in content
    assert "return $stdoutText" in content
    assert '($output -join "`n").Trim()' not in content
    assert "-Capture | ConvertFrom-Json" in content


def test_dev_up_rejects_empty_captured_stdout_explicitly() -> None:
    content = DEV_UP.read_text(encoding="utf-8")

    assert "$stdoutText = [string](" in content
    assert "$stdoutText = $stdoutText.Trim()" in content
    assert "[string]::IsNullOrWhiteSpace($stdoutText)" in content
    assert 'throw "Comando Docker não retornou a saída esperada."' in content


def test_dev_up_cleans_capture_files() -> None:
    content = DEV_UP.read_text(encoding="utf-8")

    assert "foreach ($temporaryPath in @($stdoutPath, $stderrPath))" in content
    assert "Remove-Item -LiteralPath $temporaryPath" in content
