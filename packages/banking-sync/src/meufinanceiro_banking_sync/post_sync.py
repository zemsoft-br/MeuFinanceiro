"""Explicit bounded post-sync reconciliation composition for manual banking sync."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from meufinanceiro_persistence import (
    BankingPersistenceError,
    StoredSyncStatus,
    TransactionReconciliationError,
    TransactionReconciliationResult,
)

from .models import (
    ManualSyncReconciliationExecutionError,
    ManualSyncReconciliationResult,
    ManualSyncResult,
)

_DEFAULT_RECONCILIATION_LIMIT = 500
_MAX_RECONCILIATION_LIMIT = 1_000
_RECONCILIATION_ELIGIBLE_STATUSES = frozenset(
    {
        StoredSyncStatus.SUCCEEDED,
        StoredSyncStatus.PARTIAL,
    }
)
_POST_PROCESSING_ERROR = (
    "manual banking synchronization post-processing could not be completed"
)


@runtime_checkable
class ManualSyncRunner(Protocol):
    """Minimal provider-neutral sync runner consumed by the composition boundary."""

    def run(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        idempotency_key: str,
    ) -> ManualSyncResult: ...


@runtime_checkable
class TransactionReconciliationStore(Protocol):
    """Local reconciliation boundary required after an eligible sync result."""

    def reconcile_transaction_observations(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        limit: int = _DEFAULT_RECONCILIATION_LIMIT,
    ) -> TransactionReconciliationResult: ...


class ManualBankingSyncReconciliationService:
    """Run manual sync and then at most one eligible local reconciliation batch."""

    def __init__(
        self,
        sync_runner: ManualSyncRunner,
        reconciliation_store: TransactionReconciliationStore,
        *,
        reconciliation_limit: int = _DEFAULT_RECONCILIATION_LIMIT,
    ) -> None:
        if not isinstance(sync_runner, ManualSyncRunner):
            raise TypeError("sync_runner must satisfy ManualSyncRunner")
        if not isinstance(reconciliation_store, TransactionReconciliationStore):
            raise TypeError(
                "reconciliation_store must satisfy TransactionReconciliationStore"
            )
        self._sync_runner = sync_runner
        self._reconciliation_store = reconciliation_store
        self._reconciliation_limit = _clean_reconciliation_limit(reconciliation_limit)

    def run(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        idempotency_key: str,
    ) -> ManualSyncReconciliationResult:
        sync_result = self._sync_runner.run(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
            idempotency_key=idempotency_key,
        )
        if not isinstance(sync_result, ManualSyncResult):
            raise ManualSyncReconciliationExecutionError(_POST_PROCESSING_ERROR)
        if sync_result.status not in _RECONCILIATION_ELIGIBLE_STATUSES:
            return ManualSyncReconciliationResult(
                sync_result=sync_result,
                reconciliation_result=None,
            )

        try:
            reconciliation_result = (
                self._reconciliation_store.reconcile_transaction_observations(
                    installation_id=installation_id,
                    residence_id=residence_id,
                    connection_id=connection_id,
                    limit=self._reconciliation_limit,
                )
            )
        except (TransactionReconciliationError, BankingPersistenceError):
            raise ManualSyncReconciliationExecutionError(
                _POST_PROCESSING_ERROR
            ) from None
        except Exception:
            raise ManualSyncReconciliationExecutionError(
                _POST_PROCESSING_ERROR
            ) from None

        if not isinstance(reconciliation_result, TransactionReconciliationResult):
            raise ManualSyncReconciliationExecutionError(_POST_PROCESSING_ERROR)
        return ManualSyncReconciliationResult(
            sync_result=sync_result,
            reconciliation_result=reconciliation_result,
        )


def _clean_reconciliation_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("reconciliation_limit must be an integer")
    if value < 1 or value > _MAX_RECONCILIATION_LIMIT:
        raise ValueError(
            f"reconciliation_limit must be between 1 and {_MAX_RECONCILIATION_LIMIT}"
        )
    return value


__all__ = [
    "ManualBankingSyncReconciliationService",
    "ManualSyncRunner",
    "TransactionReconciliationStore",
]
