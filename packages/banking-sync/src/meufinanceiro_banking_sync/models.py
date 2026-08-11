"""Immutable provider-neutral manual banking synchronization contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from meufinanceiro_persistence import (
    StoredSyncStatus,
    TransactionReconciliationResult,
)


class ManualSyncStopReason(StrEnum):
    COMPLETED = "completed"
    ACCOUNT_LIMIT = "account_limit"
    PAGE_LIMIT = "page_limit"
    RECORD_LIMIT = "record_limit"
    PROVIDER_ERROR = "provider_error"
    ALREADY_RUNNING = "already_running"
    REPLAYED = "replayed"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True, slots=True)
class ManualSyncLimits:
    max_accounts_per_run: int = 20
    max_pages_per_run: int = 20
    max_records_per_run: int = 5_000

    def __post_init__(self) -> None:
        for field_name in (
            "max_accounts_per_run",
            "max_pages_per_run",
            "max_records_per_run",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")


@dataclass(frozen=True, slots=True, repr=False)
class ManualSyncResult:
    sync_run_id: UUID
    status: StoredSyncStatus
    records_seen: int
    records_applied: int
    accounts_seen: int
    pages_committed: int
    stop_reason: ManualSyncStopReason

    def __post_init__(self) -> None:
        if not isinstance(self.status, StoredSyncStatus):
            raise TypeError("status must be StoredSyncStatus")
        if not isinstance(self.stop_reason, ManualSyncStopReason):
            raise TypeError("stop_reason must be ManualSyncStopReason")
        for field_name in (
            "records_seen",
            "records_applied",
            "accounts_seen",
            "pages_committed",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.records_applied > self.records_seen:
            raise ValueError("records_applied must not exceed records_seen")

    def __repr__(self) -> str:
        return (
            "ManualSyncResult("
            f"status={self.status.value!r}, records_seen={self.records_seen}, "
            f"records_applied={self.records_applied}, accounts_seen={self.accounts_seen}, "
            f"pages_committed={self.pages_committed}, "
            f"stop_reason={self.stop_reason.value!r}, <sync-run-id-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class ManualSyncReconciliationResult:
    """Redacted composition result for one sync intent plus at most one local batch."""

    sync_result: ManualSyncResult
    reconciliation_result: TransactionReconciliationResult | None

    def __post_init__(self) -> None:
        if not isinstance(self.sync_result, ManualSyncResult):
            raise TypeError("sync_result must be ManualSyncResult")
        if self.reconciliation_result is not None and not isinstance(
            self.reconciliation_result,
            TransactionReconciliationResult,
        ):
            raise TypeError(
                "reconciliation_result must be TransactionReconciliationResult or None"
            )

    @property
    def reconciliation_attempted(self) -> bool:
        return self.reconciliation_result is not None

    def __repr__(self) -> str:
        reconciliation = (
            "None"
            if self.reconciliation_result is None
            else repr(self.reconciliation_result)
        )
        return (
            "ManualSyncReconciliationResult("
            f"sync_status={self.sync_result.status.value!r}, "
            f"sync_stop_reason={self.sync_result.stop_reason.value!r}, "
            f"reconciliation_result={reconciliation}, "
            "<sync-run-id-redacted>)"
        )


class ManualSyncExecutionError(RuntimeError):
    """Sanitized orchestration failure without provider or financial material."""


class ManualSyncReconciliationExecutionError(RuntimeError):
    """Sanitized post-sync reconciliation failure after the sync run is finalized."""


__all__ = [
    "ManualSyncExecutionError",
    "ManualSyncLimits",
    "ManualSyncReconciliationExecutionError",
    "ManualSyncReconciliationResult",
    "ManualSyncResult",
    "ManualSyncStopReason",
]
