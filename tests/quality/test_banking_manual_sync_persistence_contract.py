from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PERSISTENCE = ROOT / "packages/persistence/src/meufinanceiro_persistence"
MIGRATION = (
    PERSISTENCE / "migrations/versions/0007_banking_manual_sync_persistence.py"
).read_text(encoding="utf-8")
SCHEMA = (PERSISTENCE / "schema.py").read_text(encoding="utf-8")
MODELS = (PERSISTENCE / "banking_models.py").read_text(encoding="utf-8")
STORE = (PERSISTENCE / "banking_sync_store.py").read_text(encoding="utf-8")
PUBLIC = (PERSISTENCE / "banking.py").read_text(encoding="utf-8")


def test_manual_sync_migration_is_linear_and_scoped_to_integrations() -> None:
    assert 'revision: str = "0007_banking_manual_sync"' in MIGRATION
    assert len("0007_banking_manual_sync") <= 32
    assert 'down_revision: str | None = "0006_banking_residence_fk"' in MIGRATION
    for table in ("sync_runs", "external_accounts", "sync_cursors"):
        assert f"integrations.{table}" in MIGRATION
        assert (
            f"ALTER TABLE integrations.{table} ENABLE ROW LEVEL SECURITY" in MIGRATION
        )
        assert f"ALTER TABLE integrations.{table} FORCE ROW LEVEL SECURITY" in MIGRATION
        assert f"CREATE POLICY {table}_residence_isolation" in MIGRATION
    assert "current_setting('app.current_residence_id', true)" in MIGRATION
    assert "BYPASSRLS" not in MIGRATION


def test_single_flight_and_scoped_foreign_keys_are_database_invariants() -> None:
    for source in (MIGRATION, SCHEMA):
        assert "uq_sync_runs_one_active_per_connection" in source
        assert "fk_sync_runs_connection_scope" in source
        assert "fk_external_accounts_connection_scope" in source
        assert "fk_sync_cursors_external_account_scope" in source
        assert "uq_sync_cursors_account_resource" in source
    assert "WHERE status IN ('requested','running')" in MIGRATION
    assert "ON DELETE RESTRICT" in MIGRATION
    assert "postgresql_where=text(" in SCHEMA
    assert 'ondelete="RESTRICT"' in SCHEMA


def test_manual_sync_store_has_no_provider_io_or_credentials() -> None:
    forbidden = (
        "httpx",
        "requests",
        "Pluggy",
        "BankingProvider",
        "use_enabled_credentials",
        "client_id",
        "client_secret",
        "api_key",
        "accessToken",
        "connectToken",
        "payload",
        "headers",
    )
    for token in forbidden:
        assert token not in STORE
    assert "begin_manual_sync" in STORE
    assert "replace_external_accounts" in STORE
    assert "commit_sync_cursor" in STORE


def test_sensitive_operational_values_are_redacted_from_representations() -> None:
    assert "<external-id-redacted>" in MODELS
    assert "<cursor-redacted>" in MODELS
    sync_repr = MODELS.split("class SyncRunRecord", maxsplit=1)[1].split(
        "class ExternalAccountRecord", maxsplit=1
    )[0]
    cursor_repr = MODELS.split("class SyncCursorRecord", maxsplit=1)[1].split(
        "def credential_aad", maxsplit=1
    )[0]
    assert "self.idempotency_key" not in sync_repr
    assert "self.cursor" not in cursor_repr
    assert "self.external_account_id" not in cursor_repr


def test_schema_does_not_persist_raw_provider_material() -> None:
    new_schema = SCHEMA.split("sync_runs = Table", maxsplit=1)[1]
    for forbidden in (
        "raw_payload",
        "http_payload",
        "response_body",
        "request_body",
        "authorization_header",
        "api_key",
        "connect_token",
        "client_secret",
        "account_number",
    ):
        assert forbidden not in new_schema.lower()
    assert 'Column("number_mask", String(32)' in new_schema
    assert 'Column("cursor", String(512)' in new_schema


def test_public_store_composes_manual_sync_without_http_surface() -> None:
    assert "BankingManualSyncStoreMixin" in PUBLIC
    assert "class BankingIntegrationStore(BankingManualSyncStoreMixin" in PUBLIC
    assert "FastAPI" not in STORE
    assert "APIRouter" not in STORE
    assert "@router" not in STORE
