"""Provider-neutral bounded orchestration for manual banking synchronization."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from meufinanceiro_banking import (
    AccountType,
    BankingProviderError,
    ExternalAccount,
    ExternalPage,
    ExternalTransaction,
    ProviderErrorCategory,
    TransactionStatus,
)
from meufinanceiro_persistence import (
    AppliedTransactionPage,
    BankingPersistenceError,
    ExternalAccountRecord,
    ExternalAccountSnapshot,
    StoredExternalAccountStatus,
    StoredExternalAccountType,
    StoredSyncErrorCategory,
    StoredSyncStatus,
    StoredTransactionObservationStatus,
    SyncCursorRecord,
    SyncCyclePlan,
    SyncRunRecord,
    TransactionObservationSnapshot,
)

from .models import (
    ManualSyncExecutionError,
    ManualSyncLimits,
    ManualSyncResult,
    ManualSyncStopReason,
)

Clock = Callable[[], datetime]


@runtime_checkable
class ContextualBankingReadService(Protocol):
    """Provider-neutral residence-scoped read boundary consumed by the orchestrator."""

    def list_accounts(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
    ) -> tuple[ExternalAccount, ...]: ...

    def list_transactions(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        external_account_id: str,
        cursor: str | None = None,
        changed_since: datetime | None = None,
    ) -> ExternalPage[ExternalTransaction]: ...


@runtime_checkable
class ManualSyncStore(Protocol):
    """Persistence operations required by the bounded sync boundary."""

    def begin_manual_sync(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        idempotency_key: str,
    ) -> SyncRunRecord: ...

    def mark_sync_running(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        sync_run_id: UUID,
    ) -> SyncRunRecord: ...

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
    ) -> SyncRunRecord: ...

    def replace_external_accounts(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        snapshots: tuple[ExternalAccountSnapshot, ...],
    ) -> tuple[ExternalAccountRecord, ...]: ...

    def get_sync_cursor(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        external_account_id: str,
    ) -> SyncCursorRecord | None: ...

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
    ) -> AppliedTransactionPage: ...


@runtime_checkable
class SyncFairnessStore(Protocol):
    """Optional explicit-cycle extension implemented by the canonical PostgreSQL store."""

    def prepare_sync_cycle(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        eligible_external_account_ids: tuple[str, ...],
    ) -> SyncCyclePlan: ...

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
        sync_cycle_id: UUID | None = None,
    ) -> AppliedTransactionPage: ...


_ACCOUNT_TYPES = {
    AccountType.BANK: StoredExternalAccountType.BANK,
    AccountType.CREDIT: StoredExternalAccountType.CREDIT,
    AccountType.INVESTMENT: StoredExternalAccountType.INVESTMENT,
    AccountType.LOAN: StoredExternalAccountType.LOAN,
    AccountType.OTHER: StoredExternalAccountType.OTHER,
}
_TRANSACTION_STATUSES = {
    TransactionStatus.CONFIRMED: StoredTransactionObservationStatus.CONFIRMED,
    TransactionStatus.PENDING: StoredTransactionObservationStatus.PENDING,
    TransactionStatus.INFERRED: StoredTransactionObservationStatus.INFERRED,
    TransactionStatus.DELETED: StoredTransactionObservationStatus.DELETED,
}
_PROVIDER_ERROR_CATEGORIES = {
    ProviderErrorCategory.AUTHENTICATION: StoredSyncErrorCategory.AUTHENTICATION,
    ProviderErrorCategory.AUTHORIZATION: StoredSyncErrorCategory.AUTHORIZATION,
    ProviderErrorCategory.NOT_FOUND: StoredSyncErrorCategory.NOT_FOUND,
    ProviderErrorCategory.INVALID_REQUEST: StoredSyncErrorCategory.INVALID_REQUEST,
    ProviderErrorCategory.REQUIRES_USER_ACTION: (
        StoredSyncErrorCategory.REQUIRES_USER_ACTION
    ),
    ProviderErrorCategory.RATE_LIMITED: StoredSyncErrorCategory.RATE_LIMITED,
    ProviderErrorCategory.TEMPORARILY_UNAVAILABLE: (
        StoredSyncErrorCategory.TEMPORARILY_UNAVAILABLE
    ),
    ProviderErrorCategory.CONFLICT: StoredSyncErrorCategory.CONFLICT,
    ProviderErrorCategory.UNSUPPORTED: StoredSyncErrorCategory.UNSUPPORTED,
    ProviderErrorCategory.INTERNAL: StoredSyncErrorCategory.INTERNAL,
}
_TRANSACTION_ACCOUNT_TYPES = {AccountType.BANK, AccountType.CREDIT}
_PROVIDER_REASON_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _aware_now(clock: Clock) -> datetime:
    value = clock()
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("manual sync clock must return a timezone-aware datetime")
    return value


class ManualBankingSyncService:
    """Compose contextual reads with local persistence under strict run limits."""

    def __init__(
        self,
        reader: ContextualBankingReadService,
        store: ManualSyncStore,
        *,
        limits: ManualSyncLimits | None = None,
        clock: Clock = _utc_now,
    ) -> None:
        if not isinstance(reader, ContextualBankingReadService):
            raise TypeError("reader must satisfy ContextualBankingReadService")
        if not isinstance(store, ManualSyncStore):
            raise TypeError("store must satisfy ManualSyncStore")
        if limits is not None and not isinstance(limits, ManualSyncLimits):
            raise TypeError("limits must be ManualSyncLimits")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._reader = reader
        self._store = store
        self._fairness_store = store if isinstance(store, SyncFairnessStore) else None
        self._limits = ManualSyncLimits() if limits is None else limits
        self._clock = clock

    def run(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        idempotency_key: str,
    ) -> ManualSyncResult:
        sync_run = self._store.begin_manual_sync(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
            idempotency_key=idempotency_key,
        )
        if sync_run.status.is_terminal:
            return _existing_result(sync_run, ManualSyncStopReason.REPLAYED)
        if sync_run.status is StoredSyncStatus.RUNNING:
            return _existing_result(sync_run, ManualSyncStopReason.ALREADY_RUNNING)
        if sync_run.status is not StoredSyncStatus.REQUESTED:
            raise ManualSyncExecutionError(
                "manual banking synchronization is in an invalid local state"
            )

        sync_run = self._store.mark_sync_running(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
            sync_run_id=sync_run.id,
        )
        records_seen = sync_run.records_seen
        records_applied = sync_run.records_applied
        accounts_seen = 0
        pages_committed = 0

        try:
            accounts = self._reader.list_accounts(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
            )
            accounts_seen = len(accounts)
            observed_at = _aware_now(self._clock)
            self._store.replace_external_accounts(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                snapshots=tuple(
                    _account_snapshot(account, observed_at=observed_at)
                    for account in accounts
                ),
            )

            eligible_accounts = tuple(
                account
                for account in accounts
                if account.account_type in _TRANSACTION_ACCOUNT_TYPES
            )
            cycle_id: UUID | None = None
            accounts_to_process = eligible_accounts
            if self._fairness_store is not None:
                cycle_plan = self._fairness_store.prepare_sync_cycle(
                    installation_id=installation_id,
                    residence_id=residence_id,
                    connection_id=connection_id,
                    eligible_external_account_ids=tuple(
                        account.external_account_id for account in eligible_accounts
                    ),
                )
                cycle_id = cycle_plan.cycle.id
                accounts_to_process = _pending_cycle_accounts(
                    eligible_accounts,
                    cycle_plan,
                )

            prioritized = self._prioritize_accounts_with_cursors(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                accounts=accounts_to_process,
            )

            processed_accounts = 0
            for account, persisted_cursor in prioritized:
                if processed_accounts >= self._limits.max_accounts_per_run:
                    return self._finish_partial(
                        installation_id=installation_id,
                        residence_id=residence_id,
                        connection_id=connection_id,
                        sync_run_id=sync_run.id,
                        records_seen=records_seen,
                        records_applied=records_applied,
                        accounts_seen=accounts_seen,
                        pages_committed=pages_committed,
                        reason=ManualSyncStopReason.ACCOUNT_LIMIT,
                    )

                current_cursor = (
                    None if persisted_cursor is None else persisted_cursor.cursor
                )
                seen_cursors: set[str] = (
                    set() if current_cursor is None else {current_cursor}
                )

                while True:
                    if pages_committed >= self._limits.max_pages_per_run:
                        return self._finish_partial(
                            installation_id=installation_id,
                            residence_id=residence_id,
                            connection_id=connection_id,
                            sync_run_id=sync_run.id,
                            records_seen=records_seen,
                            records_applied=records_applied,
                            accounts_seen=accounts_seen,
                            pages_committed=pages_committed,
                            reason=ManualSyncStopReason.PAGE_LIMIT,
                        )
                    if records_seen >= self._limits.max_records_per_run:
                        return self._finish_partial(
                            installation_id=installation_id,
                            residence_id=residence_id,
                            connection_id=connection_id,
                            sync_run_id=sync_run.id,
                            records_seen=records_seen,
                            records_applied=records_applied,
                            accounts_seen=accounts_seen,
                            pages_committed=pages_committed,
                            reason=ManualSyncStopReason.RECORD_LIMIT,
                        )

                    page = self._reader.list_transactions(
                        installation_id=installation_id,
                        residence_id=residence_id,
                        connection_id=connection_id,
                        external_account_id=account.external_account_id,
                        cursor=current_cursor,
                        changed_since=None,
                    )
                    if (
                        records_seen + len(page.records)
                        > self._limits.max_records_per_run
                    ):
                        return self._finish_partial(
                            installation_id=installation_id,
                            residence_id=residence_id,
                            connection_id=connection_id,
                            sync_run_id=sync_run.id,
                            records_seen=records_seen,
                            records_applied=records_applied,
                            accounts_seen=accounts_seen,
                            pages_committed=pages_committed,
                            reason=ManualSyncStopReason.RECORD_LIMIT,
                        )

                    next_cursor = page.next_cursor
                    if next_cursor is not None and next_cursor in seen_cursors:
                        raise ManualSyncExecutionError(
                            "manual banking synchronization detected an invalid "
                            "cursor sequence"
                        )

                    observations = tuple(
                        _transaction_snapshot(transaction, page.retrieved_at)
                        for transaction in page.records
                    )
                    if self._fairness_store is not None and cycle_id is not None:
                        applied = self._fairness_store.apply_transaction_page(
                            installation_id=installation_id,
                            residence_id=residence_id,
                            connection_id=connection_id,
                            external_account_id=account.external_account_id,
                            observations=observations,
                            cursor=next_cursor,
                            source_window=page.source_window,
                            committed_at=page.retrieved_at,
                            sync_cycle_id=cycle_id,
                        )
                    else:
                        applied = self._store.apply_transaction_page(
                            installation_id=installation_id,
                            residence_id=residence_id,
                            connection_id=connection_id,
                            external_account_id=account.external_account_id,
                            observations=observations,
                            cursor=next_cursor,
                            source_window=page.source_window,
                            committed_at=page.retrieved_at,
                        )
                    records_seen += applied.records_seen
                    records_applied += applied.records_applied
                    pages_committed += 1

                    if next_cursor is None:
                        break
                    seen_cursors.add(next_cursor)
                    current_cursor = next_cursor

                processed_accounts += 1

            finished = self._store.finish_sync(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                sync_run_id=sync_run.id,
                status=StoredSyncStatus.SUCCEEDED,
                records_seen=records_seen,
                records_applied=records_applied,
            )
            return ManualSyncResult(
                sync_run_id=finished.id,
                status=finished.status,
                records_seen=finished.records_seen,
                records_applied=finished.records_applied,
                accounts_seen=accounts_seen,
                pages_committed=pages_committed,
                stop_reason=ManualSyncStopReason.COMPLETED,
            )
        except BankingProviderError as error:
            return self._finish_provider_error(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                sync_run_id=sync_run.id,
                records_seen=records_seen,
                records_applied=records_applied,
                accounts_seen=accounts_seen,
                pages_committed=pages_committed,
                error=error,
            )
        except (BankingPersistenceError, ManualSyncExecutionError):
            return self._finish_internal_error(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                sync_run_id=sync_run.id,
                records_seen=records_seen,
                records_applied=records_applied,
                accounts_seen=accounts_seen,
                pages_committed=pages_committed,
            )
        except Exception:
            return self._finish_internal_error(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                sync_run_id=sync_run.id,
                records_seen=records_seen,
                records_applied=records_applied,
                accounts_seen=accounts_seen,
                pages_committed=pages_committed,
            )

    def _prioritize_accounts_with_cursors(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        accounts: tuple[ExternalAccount, ...],
    ) -> tuple[tuple[ExternalAccount, SyncCursorRecord | None], ...]:
        pending: list[tuple[ExternalAccount, SyncCursorRecord | None]] = []
        fresh: list[tuple[ExternalAccount, SyncCursorRecord | None]] = []
        for account in accounts:
            cursor = self._store.get_sync_cursor(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                external_account_id=account.external_account_id,
            )
            target = pending if cursor is not None else fresh
            target.append((account, cursor))
        return tuple(pending + fresh)

    def _finish_partial(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        sync_run_id: UUID,
        records_seen: int,
        records_applied: int,
        accounts_seen: int,
        pages_committed: int,
        reason: ManualSyncStopReason,
    ) -> ManualSyncResult:
        finished = self._store.finish_sync(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
            sync_run_id=sync_run_id,
            status=StoredSyncStatus.PARTIAL,
            records_seen=records_seen,
            records_applied=records_applied,
        )
        return ManualSyncResult(
            sync_run_id=finished.id,
            status=finished.status,
            records_seen=finished.records_seen,
            records_applied=finished.records_applied,
            accounts_seen=accounts_seen,
            pages_committed=pages_committed,
            stop_reason=reason,
        )

    def _finish_provider_error(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        sync_run_id: UUID,
        records_seen: int,
        records_applied: int,
        accounts_seen: int,
        pages_committed: int,
        error: BankingProviderError,
    ) -> ManualSyncResult:
        status = (
            StoredSyncStatus.PARTIAL
            if pages_committed > 0
            else StoredSyncStatus.FAILED
        )
        category = _PROVIDER_ERROR_CATEGORIES.get(
            error.category,
            StoredSyncErrorCategory.INTERNAL,
        )
        reason_code = _safe_provider_reason_code(error.provider_reason_code)
        try:
            finished = self._store.finish_sync(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                sync_run_id=sync_run_id,
                status=status,
                records_seen=records_seen,
                records_applied=records_applied,
                error_category=category,
                provider_reason_code=reason_code,
            )
        except Exception:
            return self._finish_internal_error(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                sync_run_id=sync_run_id,
                records_seen=records_seen,
                records_applied=records_applied,
                accounts_seen=accounts_seen,
                pages_committed=pages_committed,
            )
        return ManualSyncResult(
            sync_run_id=finished.id,
            status=finished.status,
            records_seen=finished.records_seen,
            records_applied=finished.records_applied,
            accounts_seen=accounts_seen,
            pages_committed=pages_committed,
            stop_reason=ManualSyncStopReason.PROVIDER_ERROR,
        )

    def _finish_internal_error(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        sync_run_id: UUID,
        records_seen: int,
        records_applied: int,
        accounts_seen: int,
        pages_committed: int,
    ) -> ManualSyncResult:
        status = (
            StoredSyncStatus.PARTIAL
            if pages_committed > 0
            else StoredSyncStatus.FAILED
        )
        try:
            finished = self._store.finish_sync(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                sync_run_id=sync_run_id,
                status=status,
                records_seen=records_seen,
                records_applied=records_applied,
                error_category=StoredSyncErrorCategory.INTERNAL,
            )
        except Exception:
            raise ManualSyncExecutionError(
                "manual banking synchronization could not be completed"
            ) from None
        return ManualSyncResult(
            sync_run_id=finished.id,
            status=finished.status,
            records_seen=finished.records_seen,
            records_applied=finished.records_applied,
            accounts_seen=accounts_seen,
            pages_committed=pages_committed,
            stop_reason=ManualSyncStopReason.INTERNAL_ERROR,
        )


def _pending_cycle_accounts(
    eligible_accounts: tuple[ExternalAccount, ...],
    cycle_plan: SyncCyclePlan,
) -> tuple[ExternalAccount, ...]:
    eligible_by_id = {account.external_account_id: account for account in eligible_accounts}
    if len(eligible_by_id) != len(eligible_accounts):
        raise ManualSyncExecutionError(
            "manual banking synchronization received duplicate account identities"
        )
    plan_by_id = {account.external_account_id: account for account in cycle_plan.accounts}
    if len(plan_by_id) != len(cycle_plan.accounts) or set(plan_by_id) != set(eligible_by_id):
        raise ManualSyncExecutionError(
            "manual banking synchronization cycle does not match the account snapshot"
        )
    pending_ids = {
        account.external_account_id for account in cycle_plan.pending_accounts
    }
    if cycle_plan.is_completed:
        if pending_ids:
            raise ManualSyncExecutionError(
                "completed banking synchronization cycle still has pending accounts"
            )
        return ()
    if not pending_ids and eligible_accounts:
        raise ManualSyncExecutionError(
            "open banking synchronization cycle has no pending account"
        )
    return tuple(
        account for account in eligible_accounts if account.external_account_id in pending_ids
    )


def _account_snapshot(
    account: ExternalAccount,
    *,
    observed_at: datetime,
) -> ExternalAccountSnapshot:
    return ExternalAccountSnapshot(
        external_account_id=account.external_account_id,
        account_type=_ACCOUNT_TYPES[account.account_type],
        subtype=account.subtype,
        currency=account.currency,
        status=StoredExternalAccountStatus.ACTIVE,
        observed_at=observed_at,
        name=account.name,
        number_mask=account.number_mask,
    )


def _transaction_snapshot(
    transaction: ExternalTransaction,
    observed_at: datetime,
) -> TransactionObservationSnapshot:
    return TransactionObservationSnapshot(
        external_account_id=transaction.external_account_id,
        external_resource_id=transaction.external_transaction_id,
        status=_TRANSACTION_STATUSES[transaction.status],
        provider_updated_at=transaction.provider_updated_at,
        effective_date=transaction.effective_date,
        amount=transaction.amount,
        currency=transaction.currency,
        description=transaction.description,
        category=transaction.category,
        observed_at=observed_at,
    )


def _safe_provider_reason_code(value: str | None) -> str | None:
    if value is None or not _PROVIDER_REASON_PATTERN.fullmatch(value):
        return None
    return value


def _existing_result(
    sync_run: SyncRunRecord,
    reason: ManualSyncStopReason,
) -> ManualSyncResult:
    return ManualSyncResult(
        sync_run_id=sync_run.id,
        status=sync_run.status,
        records_seen=sync_run.records_seen,
        records_applied=sync_run.records_applied,
        accounts_seen=0,
        pages_committed=0,
        stop_reason=reason,
    )


__all__ = [
    "ContextualBankingReadService",
    "ManualBankingSyncService",
    "ManualSyncStore",
    "SyncFairnessStore",
]
