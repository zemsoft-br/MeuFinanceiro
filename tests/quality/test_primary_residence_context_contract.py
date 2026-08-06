from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "packages/persistence/src/meufinanceiro_persistence/migrations/versions/0005_household_residences.py"
).read_text(encoding="utf-8")
STORE = (
    ROOT
    / "packages/persistence/src/meufinanceiro_persistence/identity_store.py"
).read_text(encoding="utf-8")
CLI = (ROOT / "apps/api/app/operator_cli.py").read_text(encoding="utf-8")
AUTH = (ROOT / "apps/api/app/api/auth.py").read_text(encoding="utf-8")
AUTH_ROUTE = (ROOT / "apps/api/app/api/routes/auth.py").read_text(encoding="utf-8")
BANKING_ADMIN_ROUTE = (
    ROOT / "apps/api/app/api/routes/banking_admin.py"
).read_text(encoding="utf-8")


def test_household_schema_has_scoped_foreign_keys_and_no_delete_grant() -> None:
    assert "identity.installation.id" in MIGRATION
    assert "identity.operators.id" in MIGRATION
    assert "uq_household_memberships_primary_operator" in MIGRATION
    assert "postgresql_where" in MIGRATION
    assert "GRANT SELECT, INSERT, UPDATE ON ALL TABLES" in MIGRATION
    assert "GRANT SELECT, INSERT, UPDATE, DELETE" not in MIGRATION


def test_bootstrap_creates_identity_and_household_in_one_store_transaction() -> None:
    method = STORE.split("def bootstrap_installation_admin", 1)[1].split(
        "def ensure_primary_residence", 1
    )[0]
    assert method.count("with self._engine.begin() as connection") == 1
    assert "identity_installation.insert()" in method
    assert "identity_operators.insert()" in method
    assert "self._insert_primary_residence(" in method


def test_legacy_repair_is_local_and_idempotent() -> None:
    assert 'subcommands.add_parser("ensure-primary-residence")' in CLI
    assert "getpass" not in CLI.split("def _ensure_primary_residence", 1)[1]
    assert "if existing is not None:" in STORE
    assert "return existing" in STORE


def test_session_context_is_derived_from_persistence() -> None:
    assert "primary_residence_id" in AUTH_ROUTE
    assert "self._primary_residence(" in STORE
    assert "require_primary_residence" in AUTH
    assert "primary residence is required" in AUTH


def test_banking_administration_never_accepts_residence_context() -> None:
    lowered = BANKING_ADMIN_ROUTE.casefold()
    assert "residence_id" not in lowered
    assert "primary_residence_id" not in lowered
    assert "require_primary_residence" not in lowered


def test_no_banking_read_or_connection_route_is_added() -> None:
    for forbidden in (
        "connect_token",
        "create_connection",
        "list_accounts",
        "list_transactions",
        "banking_pluggy_execution",
    ):
        assert forbidden not in BANKING_ADMIN_ROUTE.casefold()
