from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from meufinanceiro_banking import AccountType, ExternalAccount, ExternalPage
from meufinanceiro_banking_sync import ManualBankingSyncService, ManualSyncLimits
from meufinanceiro_persistence import (
    AppliedTransactionPage,
    StoredSyncCycleStatus,
    StoredSyncResource,
    StoredSyncStatus,
    StoredSyncTrigger,
    SyncCursorRecord,
    SyncCycleAccountRecord,
    SyncCyclePlan,
    SyncCycleRecord,
    SyncRunRecord,
)

NOW = datetime(2026, 8, 9, 18, 30, tzinfo=UTC)
INSTALLATION_ID = UUID("00000000-0000-4000-8000-000000000201")
RESIDENCE_ID = UUID("00000000-0000-4000-8000-000000000202")
CONNECTION_ID = UUID("00000000-0000-4000-8000-000000000203")


def _account(identifier: str) -> ExternalAccount:
    return ExternalAccount(
        external_account_id=identifier,
        external_connection_id="synthetic-connection",
        account_type=AccountType.BANK,
        subtype="CHECKING_ACCOUNT",
        currency="BRL",
        name="Conta sintética",
        number_mask="1234",
    )


class FairReader:
    def __init__(
        self,
        *,
        page_sequences: dict[str, list[str | None]] | None = None,
    ) -> None:
        self.accounts = (
            _account("account-a"),
            _account("account-b"),
            _account("account-c"),
        )
        self.page_sequences = {
            key: list(values) for key, values in (page_sequences or {}).items()
        }
        self.transaction_calls: list[tuple[str, str | None]] = []

    def list_accounts(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
    ) -> tuple[ExternalAccount, ...]:
        assert installation_id == INSTALLATION_ID
        assert residence_id == RESIDENCE_ID
        assert connection_id == CONNECTION_ID
        return self.accounts

    def list_transactions(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        external_account_id: str,
        cursor: str | None = None,
        changed_since: datetime | None = None,
    ) -> ExternalPage[object]:
        assert changed_since is None
        self.transaction_calls.append((external_account_id, cursor))
        sequence = self.page_sequences.get(external_account_id)
        next_cursor = None if not sequence else sequence.pop(0)
        return ExternalPage(
            records=(),
            next_cursor=next_cursor,
            source_window="FULL",
            retrieved_at=NOW,
        )


class FairStore:
    def __init__(self) -> None:
        self.cycle_id = uuid4()
        self.completed: set[str] = set()
        self.pages_committed: dict[str, int] = {}
        self.cursors: dict[str, str] = {}
        self.runs: dict[str, SyncRunRecord] = {}

    def begin_manual_sync(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        idempotency_key: str,
    ) -> SyncRunRecord:
        existing = self.runs.get(idempotency_key)
        if existing is not None:
            return existing
        run = SyncRunRecord(
            id=uuid4(),
            residence_id=residence_id,
            connection_id=connection_id,
            idempotency_key=idempotency_key,
            trigger=StoredSyncTrigger.MANUAL,
            status=StoredSyncStatus.REQUESTED,
            started_at=None,
            finished_at=None,
            attempt_count=0,
            error_category=None,
            provider_reason_code=None,
            http_status=None,
            retry_window_bucket=None,
            records_seen=0,
            records_applied=0,
            created_at=NOW,
            updated_at=NOW,
        )
        self.runs[idempotency_key] = run
        return run

    def mark_sync_running(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        sync_run_id: UUID,
    ) -> SyncRunRecord:
        key, run = next(
            (key, run) for key, run in self.runs.items() if run.id == sync_run_id
        )
        running = replace(
            run,
            status=StoredSyncStatus.RUNNING,
            started_at=NOW,
            attempt_count=1,
        )
        self.runs[key] = running
        return running

    def finish_sync(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        sync_run_id: UUID,
        status: StoredSyncStatus,
        records_seen: int,
        records_applied: int,
        error_category=None,
        provider_reason_code=None,
        http_status=None,
        retry_window_bucket=None,
    ) -> SyncRunRecord:
        key, run = next(
            (key, run) for key, run in self.runs.items() if run.id == sync_run_id
        )
        finished = replace(
            run,
            status=status,
            finished_at=NOW,
            records_seen=records_seen,
            records_applied=records_applied,
            error_category=error_category,
            provider_reason_code=provider_reason_code,
            http_status=http_status,
            retry_window_bucket=retry_window_bucket,
        )
        self.runs[key] = finished
        return finished

    def replace_external_accounts(self, **kwargs):
        return ()

    def get_sync_cursor(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        external_account_id: str,
    ) -> SyncCursorRecord | None:
        cursor = self.cursors.get(external_account_id)
        if cursor is None:
            return None
        return SyncCursorRecord(
            id=uuid4(),
            residence_id=residence_id,
            connection_id=connection_id,
            external_account_id=external_account_id,
            resource=StoredSyncResource.TRANSACTIONS,
            cursor=cursor,
            source_window="FULL",
            committed_at=NOW,
            updated_at=NOW,
        )

    def prepare_sync_cycle(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        eligible_external_account_ids: tuple[str, ...],
    ) -> SyncCyclePlan:
        status = (
            StoredSyncCycleStatus.COMPLETED
            if set(eligible_external_account_ids) <= self.completed
            else StoredSyncCycleStatus.OPEN
        )
        cycle = SyncCycleRecord(
            id=self.cycle_id,
            residence_id=residence_id,
            connection_id=connection_id,
            status=status,
            started_at=NOW,
            completed_at=NOW if status is StoredSyncCycleStatus.COMPLETED else None,
            created_at=NOW,
            updated_at=NOW,
        )
        indexed_ids = tuple(enumerate(eligible_external_account_ids))
        ordered_ids = tuple(
            account_id
            for _, account_id in sorted(
                indexed_ids,
                key=lambda item: (
                    self.pages_committed.get(item[1], 0),
                    0 if item[1] in self.cursors else 1,
                    item[0],
                ),
            )
        )
        accounts = tuple(
            SyncCycleAccountRecord(
                id=uuid4(),
                cycle_id=self.cycle_id,
                residence_id=residence_id,
                connection_id=connection_id,
                external_account_id=account_id,
                active_in_latest_snapshot=True,
                pages_committed=self.pages_committed.get(account_id, 0),
                completed_at=NOW if account_id in self.completed else None,
                created_at=NOW,
                updated_at=NOW,
            )
            for account_id in ordered_ids
        )
        return SyncCyclePlan(cycle=cycle, accounts=accounts)

    def apply_transaction_page(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        external_account_id: str,
        observations,
        cursor: str | None,
        source_window: str,
        committed_at: datetime,
        sync_cycle_id: UUID | None = None,
    ) -> AppliedTransactionPage:
        assert sync_cycle_id == self.cycle_id
        self.pages_committed[external_account_id] = (
            self.pages_committed.get(external_account_id, 0) + 1
        )
        if cursor is None:
            self.cursors.pop(external_account_id, None)
            self.completed.add(external_account_id)
        else:
            self.cursors[external_account_id] = cursor
        return AppliedTransactionPage(
            records_seen=len(observations),
            records_applied=len(observations),
            committed_at=committed_at,
        )


def _run(
    service: ManualBankingSyncService,
    key: str,
):
    return service.run(
        installation_id=INSTALLATION_ID,
        residence_id=RESIDENCE_ID,
        connection_id=CONNECTION_ID,
        idempotency_key=key,
    )


def _service(
    reader: FairReader,
    store: FairStore,
    *,
    max_accounts: int = 3,
    max_pages: int = 10,
) -> ManualBankingSyncService:
    return ManualBankingSyncService(
        reader,
        store,
        limits=ManualSyncLimits(
            max_accounts_per_run=max_accounts,
            max_pages_per_run=max_pages,
            max_records_per_run=100,
        ),
        clock=lambda: NOW,
    )


def test_account_limit_advances_to_new_accounts_across_runs() -> None:
    reader = FairReader()
    store = FairStore()
    service = _service(reader, store, max_accounts=1)

    first = _run(service, "fair-run-1")
    second = _run(service, "fair-run-2")
    third = _run(service, "fair-run-3")

    assert first.status is StoredSyncStatus.PARTIAL
    assert second.status is StoredSyncStatus.PARTIAL
    assert third.status is StoredSyncStatus.SUCCEEDED
    assert reader.transaction_calls == [
        ("account-a", None),
        ("account-b", None),
        ("account-c", None),
    ]
    assert store.completed == {"account-a", "account-b", "account-c"}


def test_terminal_page_at_page_limit_does_not_block_following_accounts() -> None:
    reader = FairReader()
    store = FairStore()
    service = _service(reader, store, max_pages=1)

    first = _run(service, "terminal-page-run-1")
    second = _run(service, "terminal-page-run-2")
    third = _run(service, "terminal-page-run-3")

    assert first.status is StoredSyncStatus.PARTIAL
    assert second.status is StoredSyncStatus.PARTIAL
    assert third.status is StoredSyncStatus.SUCCEEDED
    assert reader.transaction_calls == [
        ("account-a", None),
        ("account-b", None),
        ("account-c", None),
    ]


def test_page_limit_rotates_long_recovery_before_it_can_starve_fresh_account() -> None:
    reader = FairReader(
        page_sequences={
            "account-a": ["account-a-cursor-1", None],
        }
    )
    store = FairStore()
    service = _service(reader, store, max_pages=1)

    first = _run(service, "page-fair-run-1")
    second = _run(service, "page-fair-run-2")
    third = _run(service, "page-fair-run-3")

    assert first.status is StoredSyncStatus.PARTIAL
    assert second.status is StoredSyncStatus.PARTIAL
    assert third.status is StoredSyncStatus.PARTIAL
    assert reader.transaction_calls[:3] == [
        ("account-a", None),
        ("account-b", None),
        ("account-c", None),
    ]
    assert store.cursors["account-a"] == "account-a-cursor-1"
    assert store.completed == {"account-b", "account-c"}

    fourth = _run(service, "page-fair-run-4")
    assert fourth.status is StoredSyncStatus.SUCCEEDED
    assert reader.transaction_calls[-1] == ("account-a", "account-a-cursor-1")
    assert store.completed == {"account-a", "account-b", "account-c"}
