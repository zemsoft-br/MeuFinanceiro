from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DCO_SCRIPT = ROOT / "infra" / "scripts" / "check-dco.py"
SAFETY_SCRIPT = ROOT / "infra" / "scripts" / "check-repository-safety.py"


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)


def initialize_repository(path: Path) -> str:
    run("git", "init", "-q", str(path))
    run("git", "config", "user.name", "Quality Test", cwd=path)
    run("git", "config", "user.email", "quality@example.com", cwd=path)
    (path / "README.md").write_text("safe\n", encoding="utf-8")
    run("git", "add", "README.md", cwd=path)
    run("git", "commit", "-q", "-m", "chore: base", cwd=path)
    return run("git", "rev-parse", "HEAD", cwd=path).stdout.strip()


def test_dco_checker_accepts_signed_commit(tmp_path: Path) -> None:
    base = initialize_repository(tmp_path)
    (tmp_path / "signed.txt").write_text("signed\n", encoding="utf-8")
    run("git", "add", "signed.txt", cwd=tmp_path)
    run("git", "commit", "-q", "--signoff", "-m", "test: signed", cwd=tmp_path)
    head = run("git", "rev-parse", "HEAD", cwd=tmp_path).stdout.strip()

    result = run(sys.executable, str(DCO_SCRIPT), base, head, str(tmp_path))

    assert result.returncode == 0, result.stderr


def test_dco_checker_rejects_unsigned_commit(tmp_path: Path) -> None:
    base = initialize_repository(tmp_path)
    (tmp_path / "unsigned.txt").write_text("unsigned\n", encoding="utf-8")
    run("git", "add", "unsigned.txt", cwd=tmp_path)
    run("git", "commit", "-q", "-m", "test: unsigned", cwd=tmp_path)
    head = run("git", "rev-parse", "HEAD", cwd=tmp_path).stdout.strip()

    result = run(sys.executable, str(DCO_SCRIPT), base, head, str(tmp_path))

    assert result.returncode == 1
    assert "without a valid DCO sign-off" in result.stderr


def test_repository_safety_rejects_private_key(tmp_path: Path) -> None:
    initialize_repository(tmp_path)
    private_key_marker = "-----BEGIN " + "PRIVATE KEY-----"
    (tmp_path / "leaked.pem").write_text(
        f"{private_key_marker}\nnot-a-real-key\n",
        encoding="utf-8",
    )
    run("git", "add", "leaked.pem", cwd=tmp_path)

    result = run(sys.executable, str(SAFETY_SCRIPT), str(tmp_path))

    assert result.returncode == 1
    assert "sensitive or financial file tracked" in result.stderr
