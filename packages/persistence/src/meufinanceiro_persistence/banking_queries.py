"""Read-only local banking connection queries with residence RLS context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.engine import Engine, RowMapping
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.banking_models import StoredConnectionStatus
from meufinanceiro_persistence.schema import connections


class BankingConnectionQueryError(RuntimeError):
    """Stable sanitized failure for local banking connection queries."""


@dataclass(frozen=True, slots=True)
class LocalBankingConnectionRecord:
    """Allowlisted local metadata; provider Item identifiers are excluded."""

    id: UUID
    provider: str
    status: StoredConnectionStatus
    requires_user_action: bool
    last_successful_sync_at: datetime | None
    last_attempt_at: datetime | None
    next_refresh_allowed_at: datetime | None
    consent_expires_at: datetime | None
    disconnected_at: datetime | None
    created_at: datetime
    updated_at: datetime


_SAFE_CONNECTION_COLUMNS = (
    connections.c.id,
    connections.c.provider,
    connections.c.status,
    connections.c.requires_user_action,
    connections.c.last_successful_sync_at,
    connections.c.last_attempt_at,
    connections.c.next_refresh_allowed_at,
    connections.c.consent_expires_at,
    connections.c.disconnected_at,
    connections.c.created_at,
    connections.c.updated_at,
)


class BankingConnectionQueryStore:
    """List local connection metadata without credentials or provider I/O."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list_connections(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
    ) -> tuple[LocalBankingConnectionRecord, ...]:
        if not isinstance(installation_id, UUID):
            raise TypeError("installation_id must be UUID")
        if not isinstance(residence_id, UUID):
            raise TypeError("residence_id must be UUID")

        try:
            with self._engine.begin() as connection:
                connection.execute(
                    select(
                        func.set_config(
                            "app.current_installation_id",
                            str(installation_id),
                            True,
                        )
                    )
                )
                connection.execute(
                    select(
                        func.set_config(
                            "app.current_residence_id",
                            str(residence_id),
                            True,
                        )
                    )
                )
                rows = (
                    connection.execute(
                        select(*_SAFE_CONNECTION_COLUMNS)
                        .where(
                            connections.c.installation_id == installation_id,
                            connections.c.residence_id == residence_id,
                        )
                        .order_by(connections.c.created_at, connections.c.id)
                    )
                    .mappings()
                    .all()
                )
        except DBAPIError:
            raise BankingConnectionQueryError(
                "banking connections could not be listed"
            ) from None

        return tuple(_record(row) for row in rows)


def _record(row: RowMapping) -> LocalBankingConnectionRecord:
    return LocalBankingConnectionRecord(
        id=row["id"],
        provider=row["provider"],
        status=StoredConnectionStatus(row["status"]),
        requires_user_action=row["requires_user_action"],
        last_successful_sync_at=row["last_successful_sync_at"],
        last_attempt_at=row["last_attempt_at"],
        next_refresh_allowed_at=row["next_refresh_allowed_at"],
        consent_expires_at=row["consent_expires_at"],
        disconnected_at=row["disconnected_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
