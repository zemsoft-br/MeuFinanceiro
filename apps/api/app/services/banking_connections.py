"""Local-only banking connection summaries for authenticated residences."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from meufinanceiro_persistence import (
    LocalBankingConnectionRecord,
    StoredConnectionStatus,
)


@runtime_checkable
class LocalBankingConnectionStore(Protocol):
    def list_connections(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
    ) -> tuple[LocalBankingConnectionRecord, ...]: ...


@dataclass(frozen=True, slots=True)
class LocalBankingConnectionSummary:
    connection_id: UUID
    provider: str
    status: StoredConnectionStatus
    requires_user_action: bool
    last_successful_sync_at: datetime | None
    last_attempt_at: datetime | None
    next_refresh_allowed_at: datetime | None
    consent_expires_at: datetime | None
    disconnected_at: datetime | None
    updated_at: datetime
    reauthentication_available: bool


class BankingConnectionsService:
    """Read local connection metadata without provider I/O or credentials."""

    def __init__(
        self,
        store: LocalBankingConnectionStore,
        *,
        pluggy_reauthentication_available: bool,
    ) -> None:
        if not isinstance(store, LocalBankingConnectionStore):
            raise TypeError("store must satisfy LocalBankingConnectionStore")
        self._store = store
        self._pluggy_reauthentication_available = (
            pluggy_reauthentication_available
        )

    def list_connections(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
    ) -> tuple[LocalBankingConnectionSummary, ...]:
        records = self._store.list_connections(
            installation_id=installation_id,
            residence_id=residence_id,
        )
        return tuple(self._summary(record) for record in records)

    def _summary(
        self,
        record: LocalBankingConnectionRecord,
    ) -> LocalBankingConnectionSummary:
        reauthentication_available = (
            self._pluggy_reauthentication_available
            and record.provider == "pluggy"
            and record.status is not StoredConnectionStatus.DISCONNECTED
        )
        return LocalBankingConnectionSummary(
            connection_id=record.id,
            provider=record.provider,
            status=record.status,
            requires_user_action=record.requires_user_action,
            last_successful_sync_at=record.last_successful_sync_at,
            last_attempt_at=record.last_attempt_at,
            next_refresh_allowed_at=record.next_refresh_allowed_at,
            consent_expires_at=record.consent_expires_at,
            disconnected_at=record.disconnected_at,
            updated_at=record.updated_at,
            reauthentication_available=reauthentication_available,
        )
