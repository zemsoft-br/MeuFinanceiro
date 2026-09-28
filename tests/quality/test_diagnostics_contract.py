from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCTOR_SH = ROOT / "infra/scripts/doctor.sh"
DOCTOR_PS1 = ROOT / "infra/scripts/doctor.ps1"
EXPORT_SH = ROOT / "infra/scripts/diagnostics-export.sh"
EXPORT_PS1 = ROOT / "infra/scripts/diagnostics-export.ps1"
RUNBOOK = ROOT / "docs/runbooks/DIAGNOSTICS_AND_TROUBLESHOOTING.md"
INSTALLATION = ROOT / "docs/guides/INSTALLATION.md"
README = ROOT / "README.md"
GITIGNORE = ROOT / ".gitignore"
WORKFLOW = ROOT / ".github/workflows/diagnostics-quality.yml"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_doctors_exist_and_share_stable_status_contract() -> None:
    for path in (DOCTOR_SH, DOCTOR_PS1):
        assert path.is_file()
        content = read(path)
        assert "OK   " in content
        assert "WARN " in content
        assert "FAIL " in content
        assert "SUMMARY failures=" in content
        assert "somente leitura" in content


def test_exporters_exist_and_use_stable_bundle_contract() -> None:
    assert EXPORT_SH.is_file()
    assert EXPORT_PS1.is_file()

    shell = read(EXPORT_SH)
    powershell = read(EXPORT_PS1)
    for content in (shell, powershell):
        assert "meufinanceiro-sanitized-diagnostics" in content
        assert "meufinanceiro-diagnostics-" in content
        assert "manifest.json" in content
        assert "config-presence.txt" in content
        assert "compose-ps.json" in content
        assert "schema-revision.txt" in content
        assert "automatic_upload" in content
        assert "contains_env" in content
        assert "contains_keyring" in content
        assert "contains_database_dump" in content

    assert ".tar.gz" in shell
    assert "Compress-Archive" in powershell
    assert ".zip" in powershell
    assert "(?!\\[REDACTED\\]@)" in shell
    assert "$selected.Count -eq 0" in powershell
    assert '"[]"' in powershell


def test_powershell_scripts_use_utf8_bom_for_windows_51() -> None:
    for path in (DOCTOR_PS1, EXPORT_PS1):
        assert path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_powershell_native_capture_handles_empty_streams() -> None:
    powershell = read(EXPORT_PS1)

    assert "$exitCode = $LASTEXITCODE" in powershell
    assert "[System.IO.File]::ReadAllText($stdoutPath).Trim()" in powershell
    assert "[System.IO.File]::ReadAllText($stderrPath).Trim()" in powershell
    assert "Get-Content -LiteralPath $stdoutPath -Raw" not in powershell
    assert "Get-Content -LiteralPath $stderrPath -Raw" not in powershell


def test_powershell_schema_query_avoids_nested_native_quotes() -> None:
    powershell = read(EXPORT_PS1)

    assert '"printenv", "POSTGRES_USER"' in powershell
    assert '"printenv", "POSTGRES_DB"' in powershell
    assert '"--command", "SELECT version_num FROM alembic_version;"' in powershell
    assert '"postgres", "sh", "-c"' not in powershell
    assert 'psql --username "$POSTGRES_USER"' not in powershell


def test_collection_never_copies_or_reads_secret_files_as_text() -> None:
    shell = read(EXPORT_SH)
    powershell = read(EXPORT_PS1)

    for forbidden in (
        'cat "$ENV_FILE"',
        'cat "$KEYRING_FILE"',
        'cp "$ENV_FILE"',
        'cp "$KEYRING_FILE"',
        'source "$ENV_FILE"',
        '. "$ENV_FILE"',
    ):
        assert forbidden not in shell

    for forbidden in (
        "Get-Content -LiteralPath $EnvFile",
        "Get-Content -LiteralPath $KeyringFile",
        "Copy-Item -LiteralPath $EnvFile",
        "Copy-Item -LiteralPath $KeyringFile",
    ):
        assert forbidden not in powershell

    assert "sha256_file()" in shell
    assert 'sha256_file "$ENV_FILE"' in shell
    assert 'sha256_file "$KEYRING_FILE"' in shell
    assert 'sha256sum "$ENV_FILE"' not in shell
    assert 'sha256sum "$KEYRING_FILE"' not in shell
    assert "Get-FileHash -Algorithm SHA256 -LiteralPath $EnvFile" in powershell
    assert "Get-FileHash -Algorithm SHA256 -LiteralPath $KeyringFile" in powershell


def test_collection_is_read_only_and_avoids_raw_inspection() -> None:
    for content in (read(EXPORT_SH), read(EXPORT_PS1)):
        lowered = content.lower()
        for forbidden in (
            "compose down",
            "compose up",
            "compose build",
            "compose restart",
            "compose run",
            "docker volume rm",
            "docker system prune",
            "alembic downgrade",
            "migrate upgrade",
            "backup-create",
            "backup-verify",
        ):
            assert forbidden not in lowered
        assert "docker inspect" not in lowered
        assert "docker volume inspect" not in lowered


def test_exporters_limit_and_sanitize_logs() -> None:
    for content in (read(EXPORT_SH), read(EXPORT_PS1)):
        assert "--tail=200" in content
        assert "[REDACTED]" in content
        assert "PRIVATE KEY" in content
        assert "DATABASE_URL" in content
        assert "ACCESS_TOKEN" in content
        assert "REFRESH_TOKEN" in content
        assert "keyring.json" in content
        assert "*.dump" in content or '".dump"' in content
        assert "*.sql" in content or '".sql"' in content


def test_bundle_cleanup_and_no_automatic_upload() -> None:
    shell = read(EXPORT_SH)
    powershell = read(EXPORT_PS1)

    assert "trap cleanup EXIT" in shell
    assert 'rm -rf "$TEMP_ROOT"' in shell
    assert "finally" in powershell
    assert "Remove-Item -LiteralPath $TemporaryRoot" in powershell
    assert "upload-artifact" not in read(WORKFLOW)
    assert "automatic_upload = $false" in powershell
    assert '"automatic_upload": False' in shell


def test_doctors_do_not_mutate_the_installation() -> None:
    for content in (read(DOCTOR_SH), read(DOCTOR_PS1)):
        lowered = content.lower()
        for forbidden in (
            "compose down",
            "compose up",
            "compose build",
            "compose restart",
            "compose run",
            "volume rm",
            "migrate",
            "backup",
            "remove-item -literalpath $envfile",
            'rm -f "$env_file"',
        ):
            assert forbidden not in lowered


def test_documentation_and_quality_gate_are_linked() -> None:
    assert RUNBOOK.is_file()
    assert WORKFLOW.is_file()
    assert ".diagnostics/" in read(GITIGNORE)
    assert "DIAGNOSTICS_AND_TROUBLESHOOTING.md" in read(INSTALLATION)
    assert "DIAGNOSTICS_AND_TROUBLESHOOTING.md" in read(README)

    runbook = read(RUNBOOK)
    for topic in (
        "Docker Desktop",
        "Porta local ocupada",
        "Volume PostgreSQL não encontrado",
        "Migração ou bootstrap falhou",
        "Permissão ou ACL",
        "ROLLBACK_REQUIRES_COORDINATED_RESTORE",
    ):
        assert topic in runbook

    workflow = read(WORKFLOW)
    assert "Validate sanitized archive" in workflow
    assert "Verify collection was read-only" in workflow
    assert "DIAGNOSTICS_ADMIN_SECRET" in workflow
    assert "DIAGNOSTICS_APP_SECRET" in workflow
