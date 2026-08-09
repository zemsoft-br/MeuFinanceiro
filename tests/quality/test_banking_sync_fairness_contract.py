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


def test_orchestrator_filters_completed_accounts_before_spending_run_limits() -> None:
    assert "prepare_sync_cycle(" in SYNC_SERVICE
    assert "_pending_cycle_accounts(" in SYNC_SERVICE
    assert "cycle_plan.pending_accounts" in SYNC_SERVICE
    assert "accounts=accounts_to_process" in SYNC_SERVICE
    assert "sync_cycle_id=cycle_id" in SYNC_SERVICE


def test_terminal_page_commits_cursor_and_cycle_progress_together() -> None:
    page_method = OBSERVATION_STORE.split(
        "def apply_transaction_page",
        maxsplit=1,
    )[1].split("def _set_context", maxsplit=1)[0]
    assert "_commit_cursor(" in page_method
    assert "_complete_cycle_account(" in page_method
    assert "normalized_cursor is None" in page_method

    completion = OBSERVATION_STORE.split(
        "def _complete_cycle_account",
        maxsplit=1,
    )[1].split("def _page_cursor_already_committed", maxsplit=1)[0]
    assert "completed_at=func.transaction_timestamp()" in completion
    assert "StoredSyncCycleStatus.COMPLETED.value" in completion


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
