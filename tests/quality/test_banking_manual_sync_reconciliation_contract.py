from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "packages/banking-sync/src/meufinanceiro_banking_sync"
POST_SYNC = (PACKAGE / "post_sync.py").read_text(encoding="utf-8")
MODELS = (PACKAGE / "models.py").read_text(encoding="utf-8")
SERVICE = (PACKAGE / "service.py").read_text(encoding="utf-8")
README = (ROOT / "packages/banking-sync/README.md").read_text(encoding="utf-8")
MANUAL_SYNC_DOC = (
    ROOT / "docs/architecture/BANKING_MANUAL_SYNC_ORCHESTRATION.md"
).read_text(encoding="utf-8")
RECONCILIATION_DOC = (
    ROOT / "docs/architecture/BANKING_TRANSACTION_RECONCILIATION.md"
).read_text(encoding="utf-8")


def test_post_sync_boundary_is_explicit_and_does_not_modify_core_sync_service() -> None:
    assert "class ManualBankingSyncReconciliationService" in POST_SYNC
    assert "class ManualSyncRunner" in POST_SYNC
    assert "class TransactionReconciliationStore" in POST_SYNC
    assert "reconcile_transaction_observations" not in SERVICE
    assert "ManualBankingSyncReconciliationService" not in SERVICE


def test_only_succeeded_and_partial_sync_states_are_eligible() -> None:
    eligible = POST_SYNC.split(
        "_RECONCILIATION_ELIGIBLE_STATUSES =",
        maxsplit=1,
    )[1].split("_POST_PROCESSING_ERROR", maxsplit=1)[0]
    assert "StoredSyncStatus.SUCCEEDED" in eligible
    assert "StoredSyncStatus.PARTIAL" in eligible
    assert "StoredSyncStatus.FAILED" not in eligible
    assert "StoredSyncStatus.RUNNING" not in eligible
    assert "StoredSyncStatus.CANCELLED" not in eligible


def test_post_sync_reconciliation_is_one_bounded_batch_without_drain_loop() -> None:
    service_body = POST_SYNC.split(
        "class ManualBankingSyncReconciliationService",
        maxsplit=1,
    )[1].split("def _clean_reconciliation_limit", maxsplit=1)[0]
    assert service_body.count(".reconcile_transaction_observations(") == 1
    assert "while " not in service_body
    assert "for " not in service_body
    assert "_DEFAULT_RECONCILIATION_LIMIT = 500" in POST_SYNC
    assert "_MAX_RECONCILIATION_LIMIT = 1_000" in POST_SYNC
    assert "has_more" not in service_body


def test_post_sync_boundary_uses_only_local_scope_and_provider_neutral_contracts() -> None:
    assert "installation_id" in POST_SYNC
    assert "residence_id" in POST_SYNC
    assert "connection_id" in POST_SYNC
    assert "idempotency_key" in POST_SYNC
    forbidden = (
        "pluggy",
        "httpx",
        "fastapi",
        "flutter",
        "worker",
        "external_account_id",
        "external_resource_id",
        "stable_fingerprint",
        "identity_digest",
        "amount",
        "description",
        "category",
        "cursor",
        "changed_since",
    )
    lowered = POST_SYNC.lower()
    for token in forbidden:
        assert token.lower() not in lowered


def test_post_sync_failure_is_sanitized_and_does_not_reopen_sync_state() -> None:
    assert "ManualSyncReconciliationExecutionError" in POST_SYNC
    assert (
        "manual banking synchronization post-processing could not be completed"
        in POST_SYNC
    )
    service_body = POST_SYNC.split(
        "class ManualBankingSyncReconciliationService",
        maxsplit=1,
    )[1]
    for forbidden in (
        "finish_sync(",
        "mark_sync_running(",
        "begin_manual_sync(",
        "replace_external_accounts(",
        "apply_transaction_page(",
    ):
        assert forbidden not in service_body


def test_composed_result_repr_redacts_sync_run_id_and_uses_safe_nested_result() -> None:
    result_contract = MODELS.split(
        "class ManualSyncReconciliationResult",
        maxsplit=1,
    )[1].split("class ManualSyncExecutionError", maxsplit=1)[0]
    result_repr = result_contract.split("def __repr__", maxsplit=1)[1]
    assert "self.sync_result.sync_run_id" not in result_repr
    assert "<sync-run-id-redacted>" in result_repr
    assert "TransactionReconciliationResult" in result_contract


def test_documentation_keeps_sync_and_reconciliation_as_separate_transactions() -> None:
    for document in (README, MANUAL_SYNC_DOC, RECONCILIATION_DOC):
        assert "ManualBankingSyncReconciliationService" in document
        assert "500" in document
        assert "1000" in document
        assert "has_more" in document
    assert "não altera `ManualBankingSyncService.run`" in MANUAL_SYNC_DOC
    assert "transações PostgreSQL separadas" in RECONCILIATION_DOC
