"""Immutable redacted records for multi-run banking synchronization fairness."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from meufinanceiro_persistence.banking_models import (
    clean_external_account_id,
    require_aware,
)


class StoredSyncCycleStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True, repr=False)
class SyncCycleRecord:
    id: UUID
    residence_id: UUID
    connection_id: UUID
    status: StoredSyncCycleStatus
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.status, StoredSyncCycleStatus):
            raise TypeError("status must be StoredSyncCycleStatus")
        require_aware(self.started_at, "started_at")
        require_aware(self.completed_at, "completed_at")
        require_aware(self.created_at, "created_at")
        require_aware(self.updated_at, "updated_at")
        if self.status is StoredSyncCycleStatus.OPEN and self.completed_at is not None:
            raise ValueError("open sync cycle must not have completed_at")
        if self.status is StoredSyncCycleStatus.COMPLETED and self.completed_at is None:
            raise ValueError("completed sync cycle requires completed_at")

    def __repr__(self) -> str:
        return f"SyncCycleRecord(status={self.status.value!r}, <scope-redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class SyncCycleAccountRecord:
    id: UUID
    cycle_id: UUID
    residence_id: UUID
    connection_id: UUID
    external_account_id: str
    active_in_latest_snapshot: bool
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "external_account_id",
            clean_external_account_id(self.external_account_id),
        )
        if not isinstance(self.active_in_latest_snapshot, bool):
            raise TypeError("active_in_latest_snapshot must be bool")
        require_aware(self.completed_at, "completed_at")
        require_aware(self.created_at, "created_at")
        require_aware(self.updated_at, "updated_at")

    @property
    def is_completed(self) -> bool:
        return self.completed_at is not None

    def __repr__(self) -> str:
        return (
            "SyncCycleAccountRecord("
            f"active_in_latest_snapshot={self.active_in_latest_snapshot!r}, "
            f"is_completed={self.is_completed!r}, <external-id-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class SyncCyclePlan:
    cycle: SyncCycleRecord
    accounts: tuple[SyncCycleAccountRecord, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.cycle, SyncCycleRecord):
            raise TypeError("cycle must be SyncCycleRecord")
        seen_external_ids: set[str] = set()
        for account in self.accounts:
            if not isinstance(account, SyncCycleAccountRecord):
                raise TypeError("accounts must contain SyncCycleAccountRecord")
            if account.cycle_id != self.cycle.id:
                raise ValueError("sync cycle account belongs to another cycle")
            if (
                account.residence_id != self.cycle.residence_id
                or account.connection_id != self.cycle.connection_id
            ):
                raise ValueError("sync cycle account belongs to another scope")
            if account.external_account_id in seen_external_ids:
                raise ValueError("sync cycle plan contains duplicate accounts")
            seen_external_ids.add(account.external_account_id)

    @property
    def is_completed(self) -> bool:
        return self.cycle.status is StoredSyncCycleStatus.COMPLETED

    @property
    def pending_accounts(self) -> tuple[SyncCycleAccountRecord, ...]:
        return tuple(
            account
            for account in self.accounts
            if account.active_in_latest_snapshot and not account.is_completed
        )

    def __repr__(self) -> str:
        return (
            "SyncCyclePlan("
            f"status={self.cycle.status.value!r}, "
            f"active_accounts={sum(a.active_in_latest_snapshot for a in self.accounts)}, "
            f"pending_accounts={len(self.pending_accounts)}, <scope-redacted>)"
        )


__all__ = [
    "StoredSyncCycleStatus",
    "SyncCycleAccountRecord",
    "SyncCyclePlan",
    "SyncCycleRecord",
]
