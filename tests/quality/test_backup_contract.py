from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "infra" / "scripts" / "backup-contract.py"
CREATE_SH = ROOT / "infra" / "scripts" / "backup-create.sh"
CREATE_PS1 = ROOT / "infra" / "scripts" / "backup-create.ps1"
VERIFY_SH = ROOT / "infra" / "scripts" / "backup-verify.sh"
VERIFY_PS1 = ROOT / "infra" / "scripts" / "backup-verify.ps1"
BACKUP_ID = "meufinanceiro-20260723T120000Z-0123abcd"


def _run_contract(
    *arguments: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CONTRACT), *arguments],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def _create_dummy_bundle(bundle: Path) -> None:
    bundle.mkdir()
    (bundle / "database.dump").write_bytes(b"PGDMP\x01\x0f\x00dummy")
    (bundle / "installation.env").write_text(
        "POSTGRES_DB=meufinanceiro\nPOSTGRES_PASSWORD=do-not-leak-password\n",
        encoding="utf-8",
    )
    (bundle / "keyring.json").write_text(
        json.dumps(
            {
                "version": 1,
                "active_key_id": "k_test_active",
                "keys": {"k_test_active": "do-not-leak-key-material"},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_manifest_is_sanitized_and_bundle_validates(tmp_path: Path) -> None:
    bundle = tmp_path / BACKUP_ID
    _create_dummy_bundle(bundle)

    _run_contract(
        "create",
        "--bundle-dir",
        str(bundle),
        "--backup-id",
        BACKUP_ID,
        "--database-name",
        "meufinanceiro",
        "--schema-revision",
        "0002_demo_fixture",
    )
    result = _run_contract("validate", "--bundle-dir", str(bundle))

    safe = json.loads(result.stdout)
    manifest_text = (bundle / "manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)

    assert safe == {
        "backup_id": BACKUP_ID,
        "database_name": "meufinanceiro",
        "postgres_image": "postgres:18.4-alpine",
        "schema_revision": "0002_demo_fixture",
    }
    assert manifest["sensitive"] is True
    assert manifest["database"]["dump_format"] == "postgresql-custom"
    assert set(manifest["files"]) == {
        "database.dump",
        "installation.env",
        "keyring.json",
    }
    assert "do-not-leak-password" not in manifest_text
    assert "do-not-leak-key-material" not in manifest_text


def test_validation_rejects_tampered_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / BACKUP_ID
    _create_dummy_bundle(bundle)
    _run_contract(
        "create",
        "--bundle-dir",
        str(bundle),
        "--backup-id",
        BACKUP_ID,
        "--database-name",
        "meufinanceiro",
        "--schema-revision",
        "0002_demo_fixture",
    )
    (bundle / "database.dump").write_bytes(b"tampered")

    result = _run_contract(
        "validate",
        "--bundle-dir",
        str(bundle),
        check=False,
    )

    assert result.returncode != 0
    assert "Integridade inválida: database.dump" in result.stderr


@pytest.mark.parametrize("script", [CREATE_SH, CREATE_PS1])
def test_backup_operators_copy_binary_dump_through_docker(script: Path) -> None:
    content = script.read_text(encoding="utf-8")

    assert "pg_dump" in content
    assert "docker cp" in content or '"cp"' in content
    assert "postgresql-custom" in content or "backup-contract.py" in content
    assert "AcknowledgeSensitive" in content or "acknowledge-sensitive" in content


@pytest.mark.parametrize("script", [CREATE_PS1, VERIFY_PS1])
def test_windows_backup_operators_capture_native_output_safely(
    script: Path,
) -> None:
    content = script.read_text(encoding="utf-8")

    assert "$stdoutPath = [System.IO.Path]::GetTempFileName()" in content
    assert "$stderrPath = [System.IO.Path]::GetTempFileName()" in content
    assert "& docker @Arguments 1> $stdoutPath 2> $stderrPath" in content
    assert "foreach ($temporaryPath in @($stdoutPath, $stderrPath))" in content
    assert "return (($output -join" not in content
    assert "Comando Docker não retornou a saída esperada." in content
    assert "[AllowEmptyString()]" in content
    assert "Saída Docker vazia para $Description." in content


@pytest.mark.parametrize("script", [VERIFY_SH, VERIFY_PS1])
def test_restore_verifiers_are_isolated_and_cleanup(script: Path) -> None:
    content = script.read_text(encoding="utf-8")

    assert "--network" in content
    assert "none" in content
    assert "pg_restore" in content
    assert "PortBindings" in content
    assert "rm" in content and "--force" in content
    assert "postgres:18.4-alpine" in content or "postgres_image" in content
    assert "--publish" not in content


@pytest.mark.parametrize("script", [VERIFY_SH, VERIFY_PS1])
def test_restore_waits_for_the_final_stable_postmaster(script: Path) -> None:
    content = script.read_text(encoding="utf-8")

    assert "pg_postmaster_start_time" in content
    assert "stable" in content.lower()
    assert "5" in content
    assert content.index("pg_postmaster_start_time") < content.rindex("pg_restore")


def test_sensitive_backup_directory_is_gitignored() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert ".backups/" in gitignore.splitlines()
