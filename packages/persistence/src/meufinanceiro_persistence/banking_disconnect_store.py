"""Persistence primitives for explicit, history-preserving banking disconnects."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.banking_models import (
    BankingConnectionRecord,
    BankingPersistenceError,
    ConnectionConflictError,
    ConnectionNotFoundError,
    StoredConnectionStatus,
    StoredExternalAccountStatus,
    StoredSyncStatus,
)
from meufinanceiro_persistence.banking_sync_schema import external_accounts, sync_runs
from meufinanceiro_persistence.household_schema import household_memberships
from meufinanceiro_persistence.schema import connections

_ACTIVE_SYNC_STATUSES = (
    StoredSyncStatus.REQUESTED.value,
    StoredSyncStatus.RUNNING.value,
)
_CONNECTION_COLUMNS = (
    connections.c.id,
    connections.c.installation_id,
    connections.c.residence_id,
    connections.c.provider,
    connections.c.external_connection_id,
    connections.c.status,
    connections.c.requires_user_action,
    connections.c.last_successful_sync_at,
    connections.c.last_attempt_at,
    connections.c.next_refresh_allowed_at,
    connections.c.consent_expires_at,
    connections.c.provider_reason_code,
    connections.c.disconnected_at,
    connections.c.created_at,
    connections.c.updated_at,
)


class BankingConnectionDisconnectionStoreMixin:
    """Add serialized local disconnection primitives to the banking store."""

    _engine: Engine

    @contextmanager
    def connection_disconnection_transaction(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        connection_id: UUID,
    ) -> Iterator[BankingConnectionRecord]:
        """Hold the connection row lock through provider I/O and local finalization.

        Manual sync already acquires the same connection row with ``FOR UPDATE``
        before creating a run. Holding this row lock therefore serializes sync
        start and concurrent disconnect attempts without a second pool checkout
        or a distributed idempotency assumption.
        """
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        _require_uuid(connection_id, "connection_id")
        try:
            with self._engine.begin() as connection:
                _set_context(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )
                _require_active_member(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )
                local = _load_visible_connection(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    connection_id=connection_id,
                    for_update=True,
                )
                if local.status is not StoredConnectionStatus.DISCONNECTED:
                    _require_no_active_sync(
                        connection,
                        residence_id=residence_id,
                        connection_id=connection_id,
                    )

                yield local

                if local.status is not StoredConnectionStatus.DISCONNECTED:
                    _finalize_on_connection(
                        connection,
                        installation_id=installation_id,
                        residence_id=residence_id,
                        connection_id=connection_id,
                    )
        except BankingPersistenceError:
            raise
        except DBAPIError:
            raise BankingPersistenceError(
                "banking connection disconnection transaction failed"
            ) from None

    def prepare_connection_disconnection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        connection_id: UUID,
    ) -> BankingConnectionRecord:
        """Read and validate a candidate without performing provider I/O."""
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        _require_uuid(connection_id, "connection_id")
        try:
            with self._engine.begin() as connection:
                _set_context(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )
                _require_active_member(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )
                local = _load_visible_connection(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    connection_id=connection_id,
                )
                if local.status is not StoredConnectionStatus.DISCONNECTED:
                    _require_no_active_sync(
                        connection,
                        residence_id=residence_id,
                        connection_id=connection_id,
                    )
                return local
        except BankingPersistenceError:
            raise
        except DBAPIError:
            raise BankingPersistenceError(
                "banking connection could not be prepared for disconnection"
            ) from None

    def finalize_connection_disconnection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        connection_id: UUID,
    ) -> BankingConnectionRecord:
        """Idempotently finalize local state without any provider call."""
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        _require_uuid(connection_id, "connection_id")
        try:
            with self._engine.begin() as connection:
                _set_context(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )
                _require_active_member(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )
                local = _load_visible_connection(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    connection_id=connection_id,
                    for_update=True,
                )
                if local.status is not StoredConnectionStatus.DISCONNECTED:
                    _require_no_active_sync(
                        connection,
                        residence_id=residence_id,
                        connection_id=connection_id,
                    )
                    _finalize_on_connection(
                        connection,
                        installation_id=installation_id,
                        residence_id=residence_id,
                        connection_id=connection_id,
                    )
        except BankingPersistenceError:
            raise
        except DBAPIError:
            raise BankingPersistenceError(
                "banking connection could not be disconnected locally"
            ) from None

        return self.get_connection(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
        )


def _finalize_on_connection(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    connection_id: UUID,
) -> None:
    connection.execute(
        update(external_accounts)
        .where(
            external_accounts.c.residence_id == residence_id,
            external_accounts.c.connection_id == connection_id,
        )
        .values(
            status=StoredExternalAccountStatus.DISCONNECTED.value,
            updated_at=func.transaction_timestamp(),
        )
    )
    updated = connection.execute(
        update(connections)
        .where(
            connections.c.id == connection_id,
            connections.c.installation_id == installation_id,
            connections.c.residence_id == residence_id,
            connections.c.status != StoredConnectionStatus.DISCONNECTED.value,
        )
        .values(
            status=StoredConnectionStatus.DISCONNECTED.value,
            requires_user_action=False,
            next_refresh_allowed_at=None,
            provider_reason_code=None,
            disconnected_at=func.transaction_timestamp(),
            updated_at=func.transaction_timestamp(),
        )
    )
    if updated.rowcount != 1:
        raise ConnectionConflictError(
            "banking connection state changed during disconnection"
        )


def _set_context(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
) -> None:
    connection.execute(
        select(
            func.set_config("app.current_installation_id", str(installation_id), True),
            func.set_config("app.current_residence_id", str(residence_id), True),
            func.set_config("app.current_operator_id", str(operator_id), True),
        )
    )


def _require_active_member(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
) -> None:
    membership_id = connection.scalar(
        select(household_memberships.c.id).where(
            household_memberships.c.installation_id == installation_id,
            household_memberships.c.residence_id == residence_id,
            household_memberships.c.operator_id == operator_id,
            household_memberships.c.status == "active",
        )
    )
    if membership_id is None:
        raise ConnectionNotFoundError("banking connection was not found")


def _load_visible_connection(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    connection_id: UUID,
    for_update: bool = False,
) -> BankingConnectionRecord:
    statement = select(*_CONNECTION_COLUMNS).where(
        connections.c.id == connection_id,
        connections.c.installation_id == installation_id,
        connections.c.residence_id == residence_id,
    )
    if for_update:
        statement = statement.with_for_update()
    row = connection.execute(statement).mappings().one_or_none()
    if row is None:
        raise ConnectionNotFoundError("banking connection was not found")
    return BankingConnectionRecord(
        id=row["id"],
        installation_id=row["installation_id"],
        residence_id=row["residence_id"],
        provider=row["provider"],
        external_connection_id=row["external_connection_id"],
        status=StoredConnectionStatus(row["status"]),
        requires_user_action=row["requires_user_action"],
        last_successful_sync_at=row["last_successful_sync_at"],
        last_attempt_at=row["last_attempt_at"],
        next_refresh_allowed_at=row["next_refresh_allowed_at"],
        consent_expires_at=row["consent_expires_at"],
        provider_reason_code=row["provider_reason_code"],
        disconnected_at=row["disconnected_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _require_no_active_sync(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
) -> None:
    active_sync = connection.scalar(
        select(sync_runs.c.id).where(
            sync_runs.c.residence_id == residence_id,
            sync_runs.c.connection_id == connection_id,
            sync_runs.c.status.in_(_ACTIVE_SYNC_STATUSES),
        )
    )
    if active_sync is not None:
        raise ConnectionConflictError(
            "banking connection has an active synchronization"
        )


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


__all__ = ["BankingConnectionDisconnectionStoreMixin"]
