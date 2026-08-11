from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from meufinanceiro_banking import (
    AccountType,
    BankingProviderError,
    ExternalAccount,
    ExternalPage,
    ExternalTransaction,
    ProviderErrorCategory,
    TransactionStatus,
)
from meufinanceiro_banking_sync import (
    ManualBankingSyncService,
    ManualSyncLimits,
    ManualSyncStopReason,
)
from meufinanceiro_persistence import (
    AppliedTransactionPage,
    ExternalAccountSnapshot,
    StoredSyncErrorCategory,
    StoredSyncResource,
    StoredSyncStatus,
    StoredSyncTrigger,
    SyncCursorRecord,
    SyncRunRecord,
    TransactionObservationSnapshot,
)

NOW = datetime(2026, 8, 9, 4, 10, tzinfo=UTC)
INSTALLATION_ID = UUID("00000000-0000-4000-8000-000000000101")
RESIDENCE_ID = UUID("00000000-0000-4000-8000-000000000102")
CONNECTION_ID = UUID("00000000-0000-4000-8000-000000000103")
RUN_ID = UUID("00000000-0000-4000-8000-000000000104")


def _account(
    identifier: str,
    *,
    account_type: AccountType = AccountType.BANK,
) -> ExternalAccount:
    return ExternalAccount(
        external_account_id=identifier,
        external_connection_id="synthetic-connection",
        account_type=account_type,
        subtype="CHECKING_ACCOUNT",
        currency="BRL",
        name="Conta sintética",
        number_mask="1234",
    )


def _transaction(
    account_id: str,
    identifier: str | None,
    *,
    status: TransactionStatus = TransactionStatus.CONFIRMED,
    amount: str = "10.00",
) -> ExternalTransaction:
    return ExternalTransaction(
        external_account_id=account_id,
        external_transaction_id=identifier,
        status=status,
        provider_updated_at=NOW,
        effective_date=date(2026, 8, 9),
        amount=Decimal(amount),
        currency="BRL",
        description="Descrição sintética",
        category="synthetic",
    )


def _page(
    account_id: str,
    *,
    cursor: str | None,
    records: tuple[ExternalTransaction, ...] | None = None,
    offset_seconds: int = 0,
) -> ExternalPage[ExternalTransaction]:
    return ExternalPage(
        records=records
        if records is not None
        else (_transaction(account_id, f"tx-{account_id}-{offset_seconds}"),),
        next_cursor=cursor,
        source_window="FULL",
        retrieved_at=NOW + timedelta(seconds=offset_seconds),
    )


def _run_record(
    *,
    status: StoredSyncStatus,
    records_seen: int = 0,
    records_applied: int = 0,
) -> SyncRunRecord:
    terminal = status.is_terminal
    return SyncRunRecord(
        id=RUN_ID,
        residence_id=RESIDENCE_ID,
        connection_id=CONNECTION_ID,
        idempotency_key="manual-sync-001",
        trigger=StoredSyncTrigger.MANUAL,
        status=status,
        started_at=None if status is StoredSyncStatus.REQUESTED else NOW,
        finished_at=NOW if terminal else None,
        attempt_count=0 if status is StoredSyncStatus.REQUESTED else 1,
        error_category=None,
        provider_reason_code=None,
        http_status=None,
        retry_window_bucket=None,
        records_seen=records_seen,
        records_applied=records_applied,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeReader:
    def __init__(
        self,
        accounts: tuple[ExternalAccount, ...],
        pages: dict[
            str, list[ExternalPage[ExternalTransaction] | BankingProviderError]
        ],
        *,
        accounts_error: BankingProviderError | None = None,
    ) -> None:
        self.accounts = accounts
        self.pages = {key: list(value) for key, value in pages.items()}
        self.accounts_error = accounts_error
        self.account_calls = 0
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
        self.account_calls += 1
        if self.accounts_error is not None:
            raise self.accounts_error
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
    ) -> ExternalPage[ExternalTransaction]:
        assert installation_id == INSTALLATION_ID
        assert residence_id == RESIDENCE_ID
        assert connection_id == CONNECTION_ID
        assert changed_since is None
        self.transaction_calls.append((external_account_id, cursor))
        value = self.pages[external_account_id].pop(0)
        if isinstance(value, BankingProviderError):
            raise value
        return value


class FakeStore:
    def __init__(self, run: SyncRunRecord | None = None) -> None:
        self.run = run
        self.account_snapshots: tuple[ExternalAccountSnapshot, ...] = ()
        self.cursors: dict[str, SyncCursorRecord] = {}
        self.applied_pages: list[
            tuple[str, tuple[TransactionObservationSnapshot, ...], str | None]
        ] = []
        self.finished_calls: list[
            tuple[StoredSyncStatus, StoredSyncErrorCategory | None, str | None]
        ] = []
        self.fail_apply = False

    def begin_manual_sync(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        idempotency_key: str,
    ) -> SyncRunRecord:
        assert installation_id == INSTALLATION_ID
        assert residence_id == RESIDENCE_ID
        assert connection_id == CONNECTION_ID
        assert idempotency_key == "manual-sync-001"
        if self.run is None:
            self.run = _run_record(status=StoredSyncStatus.REQUESTED)
        return self.run

    def mark_sync_running(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        sync_run_id: UUID,
    ) -> SyncRunRecord:
        assert sync_run_id == RUN_ID
        assert self.run is not None
        self.run = replace(
            self.run,
            status=StoredSyncStatus.RUNNING,
            started_at=NOW,
            attempt_count=1,
        )
        return self.run

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
        error_category: StoredSyncErrorCategory | None = None,
        provider_reason_code: str | None = None,
        http_status: int | None = None,
        retry_window_bucket: str | None = None,
    ) -> SyncRunRecord:
        del http_status, retry_window_bucket
        assert sync_run_id == RUN_ID
        assert self.run is not None
        self.finished_calls.append((status, error_category, provider_reason_code))
        self.run = replace(
            self.run,
            status=status,
            finished_at=NOW,
            records_seen=records_seen,
            records_applied=records_applied,
            error_category=error_category,
            provider_reason_code=provider_reason_code,
        )
        return self.run

    def replace_external_accounts(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        snapshots: tuple[ExternalAccountSnapshot, ...],
    ) -> tuple[object, ...]:
        self.account_snapshots = snapshots
        return ()

    def get_sync_cursor(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        external_account_id: str,
    ) -> SyncCursorRecord | None:
        return self.cursors.get(external_account_id)

    def apply_transaction_page(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        external_account_id: str,
        observations: tuple[TransactionObservationSnapshot, ...],
        cursor: str | None,
        source_window: str,
        committed_at: datetime,
    ) -> AppliedTransactionPage:
        assert source_window == "FULL"
        if self.fail_apply:
            raise RuntimeError("synthetic persistence failure")
        self.applied_pages.append((external_account_id, observations, cursor))
        if cursor is None:
            self.cursors.pop(external_account_id, None)
        else:
            self.cursors[external_account_id] = SyncCursorRecord(
                id=uuid4(),
                residence_id=RESIDENCE_ID,
                connection_id=CONNECTION_ID,
                external_account_id=external_account_id,
                resource=StoredSyncResource.TRANSACTIONS,
                cursor=cursor,
                source_window=source_window,
                committed_at=committed_at,
                updated_at=committed_at,
            )
        return AppliedTransactionPage(
            records_seen=len(observations),
            records_applied=len(observations),
            committed_at=committed_at,
        )


def _service(
    reader: FakeReader,
    store: FakeStore,
    *,
    limits: ManualSyncLimits = ManualSyncLimits(),
) -> ManualBankingSyncService:
    return ManualBankingSyncService(reader, store, limits=limits, clock=lambda: NOW)


def _run(service: ManualBankingSyncService):
    return service.run(
        installation_id=INSTALLATION_ID,
        residence_id=RESIDENCE_ID,
        connection_id=CONNECTION_ID,
        idempotency_key="manual-sync-001",
    )


def test_success_maps_accounts_and_all_transaction_statuses_without_external_leaks() -> (
    None
):
    bank = _account("bank-account")
    other = _account("other-account", account_type=AccountType.OTHER)
    records = (
        _transaction("bank-account", "confirmed", status=TransactionStatus.CONFIRMED),
        _transaction("bank-account", "pending", status=TransactionStatus.PENDING),
        _transaction("bank-account", None, status=TransactionStatus.INFERRED),
        _transaction("bank-account", "deleted", status=TransactionStatus.DELETED),
    )
    reader = FakeReader(
        (bank, other),
        {"bank-account": [_page("bank-account", cursor=None, records=records)]},
    )
    store = FakeStore()

    result = _run(_service(reader, store))

    assert result.status is StoredSyncStatus.SUCCEEDED
    assert result.stop_reason is ManualSyncStopReason.COMPLETED
    assert result.records_seen == 4
    assert result.records_applied == 4
    assert result.accounts_seen == 2
    assert result.pages_committed == 1
    assert reader.transaction_calls == [("bank-account", None)]
    assert len(store.account_snapshots) == 2
    assert {snapshot.external_account_id for snapshot in store.account_snapshots} == {
        "bank-account",
        "other-account",
    }
    _, observations, terminal_cursor = store.applied_pages[0]
    assert terminal_cursor is None
    assert [observation.status.value for observation in observations] == [
        "CONFIRMED",
        "PENDING",
        "INFERRED",
        "DELETED",
    ]
    rendered = repr(result)
    assert "bank-account" not in rendered
    assert "confirmed" not in rendered
    assert str(RUN_ID) not in rendered


def test_terminal_replay_and_running_replay_do_not_call_provider() -> None:
    reader = FakeReader((), {})
    terminal_store = FakeStore(
        _run_record(
            status=StoredSyncStatus.SUCCEEDED,
            records_seen=3,
            records_applied=2,
        )
    )
    replay = _run(_service(reader, terminal_store))
    assert replay.stop_reason is ManualSyncStopReason.REPLAYED
    assert replay.records_seen == 3
    assert reader.account_calls == 0

    running_reader = FakeReader((), {})
    running_store = FakeStore(_run_record(status=StoredSyncStatus.RUNNING))
    running = _run(_service(running_reader, running_store))
    assert running.status is StoredSyncStatus.RUNNING
    assert running.stop_reason is ManualSyncStopReason.ALREADY_RUNNING
    assert running_reader.account_calls == 0


def test_cursor_pending_account_is_prioritized_and_account_limit_is_partial() -> None:
    first = _account("fresh-account")
    second = _account("resume-account")
    reader = FakeReader(
        (first, second),
        {
            "fresh-account": [_page("fresh-account", cursor=None)],
            "resume-account": [_page("resume-account", cursor=None)],
        },
    )
    store = FakeStore()
    store.cursors["resume-account"] = SyncCursorRecord(
        id=uuid4(),
        residence_id=RESIDENCE_ID,
        connection_id=CONNECTION_ID,
        external_account_id="resume-account",
        resource=StoredSyncResource.TRANSACTIONS,
        cursor="resume-cursor",
        source_window="FULL",
        committed_at=NOW - timedelta(minutes=1),
        updated_at=NOW - timedelta(minutes=1),
    )

    result = _run(
        _service(
            reader,
            store,
            limits=ManualSyncLimits(
                max_accounts_per_run=1,
                max_pages_per_run=20,
                max_records_per_run=5_000,
            ),
        )
    )

    assert reader.transaction_calls == [("resume-account", "resume-cursor")]
    assert result.status is StoredSyncStatus.PARTIAL
    assert result.stop_reason is ManualSyncStopReason.ACCOUNT_LIMIT


def test_page_limit_stops_before_next_external_call_and_keeps_checkpoint() -> None:
    account = _account("paged-account")
    reader = FakeReader(
        (account,),
        {
            "paged-account": [
                _page("paged-account", cursor="next-cursor"),
                _page("paged-account", cursor=None, offset_seconds=1),
            ]
        },
    )
    store = FakeStore()

    result = _run(
        _service(
            reader,
            store,
            limits=ManualSyncLimits(
                max_accounts_per_run=20,
                max_pages_per_run=1,
                max_records_per_run=5_000,
            ),
        )
    )

    assert result.status is StoredSyncStatus.PARTIAL
    assert result.stop_reason is ManualSyncStopReason.PAGE_LIMIT
    assert reader.transaction_calls == [("paged-account", None)]
    assert store.cursors["paged-account"].cursor == "next-cursor"


def test_record_limit_does_not_commit_oversized_page() -> None:
    account = _account("bounded-account")
    records = (
        _transaction("bounded-account", "tx-1"),
        _transaction("bounded-account", "tx-2"),
    )
    reader = FakeReader(
        (account,),
        {"bounded-account": [_page("bounded-account", cursor="next", records=records)]},
    )
    store = FakeStore()

    result = _run(
        _service(
            reader,
            store,
            limits=ManualSyncLimits(
                max_accounts_per_run=20,
                max_pages_per_run=20,
                max_records_per_run=1,
            ),
        )
    )

    assert result.status is StoredSyncStatus.PARTIAL
    assert result.stop_reason is ManualSyncStopReason.RECORD_LIMIT
    assert result.records_seen == 0
    assert store.applied_pages == []
    assert reader.transaction_calls == [("bounded-account", None)]


def test_provider_error_before_page_is_failed_and_sanitized() -> None:
    provider_error = BankingProviderError(
        ProviderErrorCategory.RATE_LIMITED,
        retryable=True,
        provider_reason_code="SAFE_RATE_LIMIT",
        safe_message="safe synthetic provider failure",
    )
    reader = FakeReader((), {}, accounts_error=provider_error)
    store = FakeStore()

    result = _run(_service(reader, store))

    assert result.status is StoredSyncStatus.FAILED
    assert result.stop_reason is ManualSyncStopReason.PROVIDER_ERROR
    assert store.finished_calls[-1] == (
        StoredSyncStatus.FAILED,
        StoredSyncErrorCategory.RATE_LIMITED,
        "SAFE_RATE_LIMIT",
    )
    assert "safe synthetic provider failure" not in repr(result)


def test_provider_error_after_committed_page_is_partial() -> None:
    account = _account("partial-account")
    provider_error = BankingProviderError(
        ProviderErrorCategory.TEMPORARILY_UNAVAILABLE,
        retryable=True,
        provider_reason_code="SAFE_TEMPORARY",
    )
    reader = FakeReader(
        (account,),
        {
            "partial-account": [
                _page("partial-account", cursor="next-cursor"),
                provider_error,
            ]
        },
    )
    store = FakeStore()

    result = _run(_service(reader, store))

    assert result.status is StoredSyncStatus.PARTIAL
    assert result.stop_reason is ManualSyncStopReason.PROVIDER_ERROR
    assert result.pages_committed == 1
    assert store.finished_calls[-1] == (
        StoredSyncStatus.PARTIAL,
        StoredSyncErrorCategory.TEMPORARILY_UNAVAILABLE,
        "SAFE_TEMPORARY",
    )


def test_cursor_loop_is_internal_failure_without_advancing_page() -> None:
    account = _account("loop-account")
    reader = FakeReader(
        (account,),
        {"loop-account": [_page("loop-account", cursor="same-cursor")]},
    )
    store = FakeStore()
    store.cursors["loop-account"] = SyncCursorRecord(
        id=uuid4(),
        residence_id=RESIDENCE_ID,
        connection_id=CONNECTION_ID,
        external_account_id="loop-account",
        resource=StoredSyncResource.TRANSACTIONS,
        cursor="same-cursor",
        source_window="FULL",
        committed_at=NOW - timedelta(minutes=1),
        updated_at=NOW - timedelta(minutes=1),
    )

    result = _run(_service(reader, store))

    assert result.status is StoredSyncStatus.FAILED
    assert result.stop_reason is ManualSyncStopReason.INTERNAL_ERROR
    assert store.applied_pages == []
    assert store.cursors["loop-account"].cursor == "same-cursor"


def test_limits_reject_non_positive_or_boolean_values() -> None:
    with pytest.raises(ValueError):
        ManualSyncLimits(max_accounts_per_run=0)
    with pytest.raises(ValueError):
        ManualSyncLimits(max_pages_per_run=False)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ManualSyncLimits(max_records_per_run=-1)
