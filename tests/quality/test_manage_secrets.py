from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra" / "scripts" / "manage-secrets.py"


def run(command: str, path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), command, "--path", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_secret_cli_initializes_validates_and_rotates_without_printing_material(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".secrets" / "keyring.json"

    initialized = run("init", path)
    validated = run("validate", path)
    rotated = run("rotate", path)

    assert initialized.returncode == 0, initialized.stderr
    assert validated.returncode == 0, validated.stderr
    assert rotated.returncode == 0, rotated.stderr
    assert "retained_keys=1" in initialized.stdout
    assert "retained_keys=2" in rotated.stdout
    assert '"keys"' not in initialized.stdout
    assert "material" not in initialized.stdout.lower()
    assert path.exists()
