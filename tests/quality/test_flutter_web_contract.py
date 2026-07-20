from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_flutter_web_source_contract() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "infra" / "scripts" / "check-flutter-web-contract.py"),
            "--source-only",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
