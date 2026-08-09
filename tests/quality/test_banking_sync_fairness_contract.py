from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "packages/persistence/src/meufinanceiro_persistence/migrations/versions/0009_banking_sync_fairness.py"
).read_text(encoding="utf-8")
FAIRNESS_SCHEMA = (
    ROOT
    / "packages/persistence/src/meufinanceiro_persistence/banking_fairness_schema.py"
).read_text(encoding="utf-8")
FAIRNESS_STORE = (
    ROOT
    / "packages/persistence/src/meufinanceiro_persistence/banking_fairness_store.py"
).read_text(encoding="utf-8")
BANKING_STORE = (
    ROOT / "packages/persistence/src/meufinanceiro_persistence/banking.py"
).read_text(encoding="utf-8")
OBSERVATION_STORE = (
    ROOT
    / "packages/persistence/src/meufinanceiro_persistence/banking_observation_store.py"
).read_text(encoding="utf-8")
SYNC_SERVICE = (
    ROOT / "packages/banking-sync/src/meufinanceiro_banking_sync/service.py"
).read_text(encoding="utf-8")


def test_fairness_uses_explicit_residence_scoped_cycle_state() -> None:
    assert "CREATE TABLE integrations.sync_cycles" in MIGRATION
    assert "CREATE TABLE integrations.sync_cycle_accounts" in MIGRATION
    assert "ENABLE ROW LEVEL SECURITY" in MIGRATION
    assert "FORCE ROW LEVEL SECURITY" in MIGRATION
    assert "app.current_residence_id" in MIGRATION
    assert "uq_sync_cycles_one_open_per_connection" in MIGRATION
    assert "fk_sync_cycle_accounts_cycle_scope" in MIGRATION
    assert "fk_sync_cycle_accounts_external_account_scope" in MIGRATION
    assert "uq_external_accounts_local_scope" in MIGRATION
    assert "external_account_record_id uuid NOT NULL" in MIGRATION
    assert "external_account_id varchar" not in MIGRATION
    assert "active_in_latest_snapshot" in FAIRNESS_SCHEMA


def test_fairness_never_encodes_local_state_inside_provider_cursor() -> None:
    combined = f"{FAIRNESS_STORE}\n{SYNC_SERVICE}"
    for forbidden in (
        "cursor sentinel",
        "sentinel_cursor",
        "__COMPLETED__",
        "FAIRNESS_CURSOR",
    ):
        assert forbidden not in combined
    assert "prepare_sync_cycle" in FAIRNESS_STORE
    assert "completed_at" in FAIRNESS_STORE


def test_new_cycle_resets_only_previous_cycle_recovery_material() -> None:
    assert "_has_completed_cycle(" in FAIRNESS_STORE
    assert "_clear_previous_cycle_cursors(" in FAIRNESS_STORE
    reset = FAIRNESS_STORE.split(
        "def _clear_previous_cycle_cursors",
        maxsplit=1,
    )[1].split("def _active_cycle_accounts", maxsplit=1)[0]
    assert "delete(sync_cursors)" in reset
    assert "StoredSyncResource.TRANSACTIONS.value" in reset
    assert "residence_id == residence_id" in reset
    assert "connection_id == connection_id" in reset


def test_fairness_orders_least_served_accounts_before_recovery_priority() -> None:
    assert "pages_committed" in MIGRATION
    assert "pages_committed=0" in FAIRNESS_STORE
    ordering = FAIRNESS_STORE.split("def _active_cycle_accounts", maxsplit=1)[1].split(
        "def _cycle_record", maxsplit=1
    )[0]
    assert "sync_cycle_accounts.c.pages_committed" in ordering
    assert "cursor_priority" in ordering
    assert ordering.index("sync_cycle_accounts.c.pages_committed") < ordering.rindex(
        "cursor_priority"
    )


def test_orchestrator_preserves_persistent_fair_order_before_spending_limits() -> None:
    assert "prepare_sync_cycle(" in SYNC_SERVICE
    assert "_pending_cycle_accounts(" in SYNC_SERVICE
    assert "cycle_plan.pending_accounts" in SYNC_SERVICE
    assert "preserve_input_order=preserve_fair_order" in SYNC_SERVICE
    assert "accounts=accounts_to_process" in SYNC_SERVICE
    assert "sync_cycle_id=cycle_id" in SYNC_SERVICE


def test_terminal_page_commits_cursor_and_cycle_progress_together() -> None:
    page_method = OBSERVATION_STORE.split(
        "def apply_transaction_page",
        maxsplit=1,
    )[1].split("def _set_context", maxsplit=1)[0]
    assert "_commit_cursor(" in page_method
    assert "_advance_cycle_account(" in page_method
    assert "terminal=normalized_cursor is None" in page_method

    progress = OBSERVATION_STORE.split(
        "def _advance_cycle_account",
        maxsplit=1,
    )[1].split("def _page_cursor_already_committed", maxsplit=1)[0]
    assert "pages_committed=sync_cycle_accounts.c.pages_committed + 1" in progress
    assert "completed_at=func.transaction_timestamp()" in progress
    assert "StoredSyncCycleStatus.COMPLETED.value" in progress


def test_canonical_store_composes_fairness_extension() -> None:
    declaration = BANKING_STORE.split(
        "class BankingIntegrationStore(",
        maxsplit=1,
    )[1].split("):", maxsplit=1)[0]
    assert "BankingSyncFairnessStoreMixin" in declaration


def test_fairness_result_boundaries_do_not_add_external_material() -> None:
    public_result_block = SYNC_SERVICE.split(
        "class ManualBankingSyncService",
        maxsplit=1,
    )[0]
    for forbidden in (
        "fingerprint",
        "amount",
        "description",
        "client_secret",
        "item_id",
    ):
        assert forbidden not in public_result_block.lower()
