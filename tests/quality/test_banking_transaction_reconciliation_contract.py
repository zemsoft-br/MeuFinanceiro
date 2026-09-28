from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PERSISTENCE = ROOT / "packages/persistence/src/meufinanceiro_persistence"
MIGRATION = (
    PERSISTENCE / "migrations/versions/0010_banking_tx_reconciliation.py"
).read_text(encoding="utf-8")
SCHEMA = (PERSISTENCE / "banking_reconciliation_schema.py").read_text(encoding="utf-8")
MODELS = (PERSISTENCE / "banking_reconciliation_models.py").read_text(encoding="utf-8")
STORE = (PERSISTENCE / "banking_reconciliation_store.py").read_text(encoding="utf-8")
BANKING = (PERSISTENCE / "banking.py").read_text(encoding="utf-8")


def test_reconciliation_schema_is_residence_scoped_and_local_identity_based() -> None:
    assert 'revision: str = "0010_banking_tx_reconciliation"' in MIGRATION
    assert 'down_revision: str | None = "0009_banking_sync_fairness"' in MIGRATION
    assert "CREATE TABLE integrations.reconciled_transactions" in MIGRATION
    assert "CREATE TABLE integrations.reconciled_transaction_sources" in MIGRATION
    assert "uq_external_observations_local_scope" in MIGRATION
    assert "external_account_record_id uuid NOT NULL" in MIGRATION
    assert "identity_digest varchar(64) NOT NULL" in MIGRATION
    assert "fk_reconciled_transactions_account_scope" in MIGRATION
    assert "fk_reconciled_transactions_source_scope" in MIGRATION
    assert "fk_reconciled_transaction_sources_target_scope" in MIGRATION
    assert "ENABLE ROW LEVEL SECURITY" in MIGRATION
    assert "FORCE ROW LEVEL SECURITY" in MIGRATION
    assert "app.current_residence_id" in MIGRATION
    assert "uq_reconciled_transactions_identity" in MIGRATION
    assert "ix_external_observations_reconciliation_scan" in MIGRATION


def test_reconciliation_identity_never_uses_financial_fields_or_fuzzy_matching() -> (
    None
):
    identity = STORE.split("def _identity(", maxsplit=1)[1].split(
        "def _stored_status", maxsplit=1
    )[0]
    assert "external_resource_id" in identity
    assert "stable_fingerprint" in identity
    assert "external_account_record_id" in identity
    assert '"transactions"' in identity
    assert "sha256" in identity
    for forbidden in (
        "amount",
        "description",
        "category",
        "effective_date",
        "similarity",
        "levenshtein",
        "fuzzy",
    ):
        assert forbidden not in identity.lower()


def test_reconciliation_is_local_bounded_and_does_not_reuse_provider_cursor() -> None:
    assert "_DEFAULT_RECONCILIATION_LIMIT = 500" in STORE
    assert "_MAX_RECONCILIATION_LIMIT = 1_000" in STORE
    assert "normalized_limit + 1" in STORE
    assert "has_more = len(rows) > normalized_limit" in STORE
    assert "reconciled_transaction_sources" in STORE
    assert "observation_updated_at" in STORE
    assert "external_observations.c.updated_at" in STORE
    assert "external_observations.c.id" in STORE
    assert ".with_for_update(of=external_observations)" in STORE
    for forbidden in (
        "sync_cursors",
        "provider_cursor",
        "changed_since",
        "httpx",
        "requests",
        "fastapi",
        "pluggy",
        "flutter",
        "worker",
    ):
        assert forbidden not in STORE.lower()


def test_temporal_reconciliation_is_fail_closed_and_deleted_is_only_explicit_state() -> (
    None
):
    assert "current_observed_at > observed_at" in STORE
    assert "current_observed_at == observed_at" in STORE
    assert "incompatible observations at the same time" in STORE
    assert "source progress would regress" in STORE
    assert "StoredTransactionObservationStatus(value)" in STORE
    assert "DELETED" in MODELS or "StoredTransactionObservationStatus" in MODELS
    for forbidden in (
        "missing means deleted",
        "absence means deleted",
        "infer_deleted",
        "mark_missing_deleted",
    ):
        assert forbidden not in STORE.lower()


def test_reconciliation_result_and_record_repr_are_redacted() -> None:
    record = MODELS.split("class ReconciledTransactionRecord", maxsplit=1)[1].split(
        "class TransactionReconciliationResult", maxsplit=1
    )[0]
    record_repr = record.split("def __repr__", maxsplit=1)[1]
    assert "self.identity_digest" not in record_repr
    assert "self.source_observation_id" not in record_repr
    assert "self.external_account_record_id" not in record_repr
    assert "<identity-and-scope-redacted>" in record_repr

    result = MODELS.split("class TransactionReconciliationResult", maxsplit=1)[1]
    for forbidden in (
        "external_resource_id",
        "stable_fingerprint",
        "identity_digest",
        "amount",
        "description",
        "category",
        "cursor",
    ):
        assert forbidden not in result.lower()


def test_canonical_banking_store_composes_reconciliation_boundary() -> None:
    declaration = BANKING.split(
        "class BankingIntegrationStore(",
        maxsplit=1,
    )[1].split("):", maxsplit=1)[0]
    assert "BankingTransactionReconciliationStoreMixin" in declaration
    assert "TransactionReconciliationResult" in BANKING
    assert "TransactionReconciliationConflictError" in BANKING
