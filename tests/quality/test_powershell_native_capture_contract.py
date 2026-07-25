"""Regression contract for Windows PowerShell native process capture."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POWERSHELL_SCRIPTS = (
    ROOT / "infra/scripts/update-foundation.ps1",
    ROOT / "infra/scripts/backup-create.ps1",
    ROOT / "infra/scripts/backup-verify.ps1",
)


def test_native_capture_handles_empty_output_on_windows_powershell() -> None:
    for path in POWERSHELL_SCRIPTS:
        content = path.read_text(encoding="utf-8")
        assert "[string]::Concat(" not in content
        assert "([string]$stderrText).Trim()" in content
        assert "([string]$stdoutText).Trim()" in content
