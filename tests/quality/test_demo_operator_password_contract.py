from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "compose.yaml"
UNIX_SCRIPT = ROOT / "infra/scripts/demo-up.sh"
WINDOWS_SCRIPT = ROOT / "infra/scripts/demo-up.ps1"
CLI = ROOT / "packages/persistence/src/meufinanceiro_persistence/demo_cli.py"
RUNBOOK = ROOT / "docs/runbooks/DEMO_MODE.md"


def test_compose_mounts_demo_operator_password_as_private_secret() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")

    assert "DEMO_OPERATOR_PASSWORD_FILE: /run/secrets/demo_operator_password" in compose
    assert "demo_operator_password:" in compose
    assert "DEMO_OPERATOR_PASSWORD_FILE_HOST" in compose
    assert "${DEMO_OPERATOR_PASSWORD:?" not in compose
    assert "DEMO_OPERATOR_PASSWORD: ${" not in compose


def test_demo_scripts_generate_reuse_purge_and_migrate_operator_password() -> None:
    unix = UNIX_SCRIPT.read_text(encoding="utf-8")
    windows = WINDOWS_SCRIPT.read_text(encoding="utf-8")

    assert 'OPERATOR_PASSWORD_FILE="$SECRETS_DIR/operator_password.txt"' in unix
    assert 'generate_password > "$OPERATOR_PASSWORD_FILE"' in unix
    assert 'chmod 600 "$OPERATOR_PASSWORD_FILE"' in unix
    assert 'cat "$OPERATOR_PASSWORD_FILE"' in unix
    assert 'rm -rf "$STATE_DIR"' in unix
    assert "migrate_legacy_operator_password" in unix
    assert "grep -v '^DEMO_OPERATOR_PASSWORD='" in unix
    assert 'if [ "$current_password" != "$legacy_password" ]; then' in unix
    assert "nenhuma fonte foi alterada" in unix
    assert "meufinanceiro-demo-ci-only" not in unix
    assert "DEMO_OPERATOR_PASSWORD is obrigatória" not in unix

    assert '$OperatorPasswordFile = Join-Path $SecretsDir "operator_password.txt"' in windows
    assert '"$(New-RandomPassword)`n"' in windows
    assert "Set-PrivateAcl -Path $OperatorPasswordFile" in windows
    assert 'Write-Host "Senha demo: $OperatorPassword"' in windows
    assert "Remove-Item $StateDir -Recurse -Force" in windows
    assert "^DEMO_OPERATOR_PASSWORD=" in windows
    assert "$ExistingOperatorPassword -cne $LegacyPassword" in windows
    assert "diverge do secret file existente" in windows
    assert "DEMO_OPERATOR_PASSWORD_FILE_HOST=.demo/secrets/operator_password.txt" in windows
    assert 'GetEnvironmentVariable("DEMO_OPERATOR_PASSWORD")' not in windows


def test_demo_cli_prefers_single_explicit_password_source() -> None:
    cli = CLI.read_text(encoding="utf-8")

    assert "demo_operator_password_file: Path | None = None" in cli
    assert "configure only one of DEMO_OPERATOR_PASSWORD" in cli
    assert "password_file.read_text" in cli
    assert "get_secret_value()" in cli
    assert "print(operator_password" not in cli


def test_demo_runbook_documents_generated_local_credential() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")

    assert ".demo/secrets/operator_password.txt" in runbook
    assert "gerada automaticamente" in runbook
    assert "Docker secret" in runbook
    assert "não precisa definir `DEMO_OPERATOR_PASSWORD`" in runbook
    assert "ambiente demo antigo" in runbook
    assert "remove a linha `DEMO_OPERATOR_PASSWORD=`" in runbook
    assert "divergirem" in runbook
    assert "falha fechado" in runbook
