from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PERSISTENCE = ROOT / "packages/persistence/src/meufinanceiro_persistence"
MIGRATION = (
    PERSISTENCE / "migrations/versions/0008_banking_transaction_observations.py"
).read_text(encoding="utf-8")
SCHEMA = (PERSISTENCE / "banking_observation_schema.py").read_text(encoding="utf-8")
MODELS = (PERSISTENCE / "banking_observation_models.py").read_text(encoding="utf-8")
STORE = (PERSISTENCE / "banking_observation_store.py").read_text(encoding="utf-8")
PUBLIC = (PERSISTENCE / "banking.py").read_text(encoding="utf-8")


def test_observation_migration_is_linear_bounded_and_residence_scoped() -> None:
    revision = "0008_banking_tx_observations"
    assert len(revision) <= 32
    assert f'revision: str = "{revision}"' in MIGRATION
    assert 'down_revision: str | None = "0007_banking_manual_sync"' in MIGRATION
    assert "CREATE TABLE integrations.external_observations" in MIGRATION
    assert "ENABLE ROW LEVEL SECURITY" in MIGRATION
    assert "FORCE ROW LEVEL SECURITY" in MIGRATION
    assert "external_observations_residence_isolation" in MIGRATION
    assert "current_setting('app.current_residence_id', true)" in MIGRATION
    assert "BYPASSRLS" not in MIGRATION


def test_observation_schema_preserves_identity_and_history_invariants() -> None:
    for source in (MIGRATION, SCHEMA):
        assert "fk_external_observations_account_scope" in source
        assert "uq_external_observations_fingerprint" in source
        assert "uq_external_observations_external_resource" in source
        assert "ck_external_observations_inferred_identity" in source
        assert "ck_external_observations_amount_finite" in source
        assert "normalized_payload_version" in source
        assert "stable_fingerprint" in source
    assert "ON DELETE RESTRICT" in MIGRATION
    assert 'ondelete="RESTRICT"' in SCHEMA
    assert "external_resource_id IS NOT NULL" in MIGRATION
    assert "external_resource_id IS NOT NULL" in SCHEMA
    assert "status <> 'INFERRED' OR external_resource_id IS NULL" in MIGRATION
    assert "status <> 'INFERRED' OR external_resource_id IS NULL" in SCHEMA
    assert "amount::text NOT IN ('NaN','Infinity','-Infinity')" in MIGRATION
    assert "amount::text NOT IN ('NaN', 'Infinity', '-Infinity')" in SCHEMA


def test_amount_and_fingerprint_are_normalized_inside_persistence_boundary() -> None:
    assert "Decimal" in MODELS
    assert "float" not in MODELS
    assert "hashlib.sha256" in MODELS
    assert "meufinanceiro:transaction-observation:v1" in MODELS
    fingerprint_body = MODELS.split("def stable_fingerprint", maxsplit=1)[1].split(
        "def normalized_payload_version",
        maxsplit=1,
    )[0]
    assert "status" not in fingerprint_body
    assert "_MAX_AMOUNT_PRECISION = 24" in MODELS
    assert "_MAX_AMOUNT_SCALE = 8" in MODELS
    assert "value.as_tuple()" in MODELS
    assert "value.normalize()" not in MODELS
    assert "if not isinstance(raw_exponent, int)" in MODELS
    assert "inferred observation cannot claim a provider resource ID" in MODELS


def test_page_and_cursor_are_committed_inside_one_database_transaction() -> None:
    method = STORE.split("def apply_transaction_page", maxsplit=1)[1].split(
        "def _set_context",
        maxsplit=1,
    )[0]
    assert "with self._engine.begin() as connection" in method
    assert "_lock_external_account(" in method
    assert "_page_cursor_already_committed(" in method
    assert "postgresql_insert(external_observations)" in method
    assert "_commit_cursor(" in method
    assert method.index("_page_cursor_already_committed(") < method.index(
        "postgresql_insert(external_observations)"
    )
    assert method.index("postgresql_insert(external_observations)") < method.index(
        "_commit_cursor("
    )
    assert "observation.observed_at > committed_at" in method
    assert "external_observations.c.last_seen_at" in method
    assert "< observation.observed_at" in method
    assert "records_applied=0" in method
    assert "RowMapping | None" in STORE


def test_observation_store_has_no_provider_io_http_or_credentials() -> None:
    for forbidden in (
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
        "APIRouter",
        "FastAPI",
        "@router",
    ):
        assert forbidden not in STORE


def test_raw_provider_material_is_not_persisted_or_rendered() -> None:
    combined_schema = f"{MIGRATION}\n{SCHEMA}".lower()
    for forbidden in (
        "raw_payload",
        "response_body",
        "request_body",
        "authorization_header",
        "provider_message",
        "api_key",
        "connect_token",
        "client_secret",
    ):
        assert forbidden not in combined_schema
    assert "<financial-material-redacted>" in MODELS

    snapshot_class = MODELS.split(
        "class TransactionObservationSnapshot",
        maxsplit=1,
    )[1].split("class TransactionObservationRecord", maxsplit=1)[0]
    snapshot_repr = snapshot_class.split("def __repr__", maxsplit=1)[1]
    record_class = MODELS.split(
        "class TransactionObservationRecord",
        maxsplit=1,
    )[1].split("class AppliedTransactionPage", maxsplit=1)[0]
    record_repr = record_class.split("def __repr__", maxsplit=1)[1]
    for representation in (snapshot_repr, record_repr):
        for sensitive_attr in (
            "self.amount",
            "self.description",
            "self.external_account_id",
            "self.external_resource_id",
            "self.stable_fingerprint",
        ):
            assert sensitive_attr not in representation


def test_public_store_composes_atomic_observation_boundary() -> None:
    assert "BankingTransactionObservationStoreMixin" in PUBLIC
    assert "BankingManualSyncStoreMixin" in PUBLIC
    assert "AppliedTransactionPage" in PUBLIC
    assert "TransactionObservationSnapshot" in PUBLIC
