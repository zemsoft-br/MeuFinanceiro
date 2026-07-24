from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPDATE_SH = ROOT / "infra/scripts/update-foundation.sh"
UPDATE_PS1 = ROOT / "infra/scripts/update-foundation.ps1"
RUNBOOK = ROOT / "docs/runbooks/SAFE_UPDATE_AND_ROLLBACK.md"
GITIGNORE = ROOT / ".gitignore"
README = ROOT / "README.md"
INSTALLATION = ROOT / "docs/guides/INSTALLATION.md"
SAFE_UPDATE_QUALITY = ROOT / ".github/workflows/safe-update-quality.yml"
TEMPORARY_FINALIZER = ROOT / ".github/workflows/temporary-finalize-safe-update.yml"
TEMPORARY_SMOKE_FIX = ROOT / ".github/workflows/temporary-fix-update-smoke.yml"
TEMPORARY_POWERSHELL_PAYLOAD = ROOT / ".tmp/update-foundation.ps1.b64"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_update_operators_exist_and_require_sensitive_acknowledgement() -> None:
    assert UPDATE_SH.is_file()
    assert UPDATE_PS1.is_file()
    assert "--acknowledge-sensitive" in read(UPDATE_SH)
    assert "AcknowledgeSensitive" in read(UPDATE_PS1)


def test_update_operators_require_fast_forward_and_clean_checkout() -> None:
    shell = read(UPDATE_SH)
    powershell = read(UPDATE_PS1)

    assert "merge-base --is-ancestor" in shell
    assert "diff --quiet" in shell
    assert "diff --cached --quiet" in shell
    assert '"merge-base", "--is-ancestor"' in powershell
    assert '"status", "--porcelain", "--untracked-files=no"' in powershell


def test_update_operators_create_and_verify_backup_before_apply() -> None:
    for content in (read(UPDATE_SH), read(UPDATE_PS1)):
        assert "backup-create" in content
        assert "backup-verify" in content
        assert "PREPARED" in content
        assert "backup_verified" in content


def test_update_operators_use_worktree_lock_and_atomic_state() -> None:
    shell = read(UPDATE_SH)
    powershell = read(UPDATE_PS1)

    assert ".updates" in shell
    assert "update.lock" in shell
    assert "worktree add --detach" in shell
    assert "os.replace" in shell
    assert '"worktree", "add", "--detach"' in powershell
    assert "Move-Item" in powershell
    assert "update.lock" in powershell


def test_update_state_contract_is_sanitized() -> None:
    for content in (read(UPDATE_SH), read(UPDATE_PS1)):
        for status in (
            "FAILED_PRECHECK",
            "PREPARED",
            "APPLIED",
            "ROLLED_BACK",
            "ROLLBACK_REQUIRES_COORDINATED_RESTORE",
        ):
            assert status in content
        assert "backup_id" in content
        assert "volume_fingerprint_sha256" in content
        assert "POSTGRES_PASSWORD" not in content
        assert "APP_DATABASE_PASSWORD" not in content
        assert "DATABASE_URL" not in content


def test_schema_change_blocks_destructive_rollback() -> None:
    for content in (read(UPDATE_SH), read(UPDATE_PS1)):
        assert "ROLLBACK_REQUIRES_COORDINATED_RESTORE" in content
        assert "schema_changed_or_unknown" in content
        assert "downgrade" not in content.lower()
        assert "down --volumes" not in content
        assert "docker volume rm" not in content


def test_update_preserves_configuration_and_volume_identity() -> None:
    for content in (read(UPDATE_SH), read(UPDATE_PS1)):
        assert "EnvHash" in content or "ENV_HASH" in content
        assert "KeyringHash" in content or "KEYRING_HASH" in content
        assert "meufinanceiro_postgres_data" in content
        assert "VolumeFingerprint" in content or "VOLUME_FINGERPRINT" in content


def test_unix_smoke_uses_external_compose_configuration() -> None:
    shell = read(UPDATE_SH)

    assert 'COMPOSE_ENV_FILES="$ENV_FILE"' in shell
    assert 'APP_KEYRING_FILE_HOST="$KEYRING_FILE"' in shell
    assert 'cd "$project_dir"' in shell


def test_update_contract_is_linked_and_ignored() -> None:
    assert ".updates/" in read(GITIGNORE)
    assert "SAFE_UPDATE_AND_ROLLBACK.md" in read(README)
    assert "SAFE_UPDATE_AND_ROLLBACK.md" in read(INSTALLATION)
    assert "update-foundation.sh" in read(SAFE_UPDATE_QUALITY)
    assert "update-foundation.ps1" in read(SAFE_UPDATE_QUALITY)
    assert RUNBOOK.is_file()


def test_temporary_finalization_artifacts_are_absent() -> None:
    assert not TEMPORARY_FINALIZER.exists()
    assert not TEMPORARY_SMOKE_FIX.exists()
    assert not TEMPORARY_POWERSHELL_PAYLOAD.exists()


def test_safe_update_quality_exercises_apply_and_rollback_states() -> None:
    workflow = read(SAFE_UPDATE_QUALITY)
    assert "Validate safe source update" in workflow
    assert "Validate rollback with unchanged schema" in workflow
    assert "Validate schema-change rollback block" in workflow
    assert "target_started_and_smoke_passed" in workflow
    assert "target_failed_schema_unchanged" in workflow
    assert "schema_changed_or_unknown" in workflow
