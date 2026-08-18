"""Persistence primitives for explicit, history-preserving banking disconnects."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy import Connection, Engine, func, select, update
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.banking_connection_lock import (
    connection_operation_lock_key,
)
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


class _ConnectionReader(Protocol):
    def get_connection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
    ) -> BankingConnectionRecord: ...


class BankingConnectionDisconnectionStoreMixin:
    """Add serialized local disconnection primitives to the banking store."""

    _engine: Engine

    @contextmanager
    def hold_connection_disconnection_lock(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        connection_id: UUID,
    ) -> Iterator[None]:
        """Serialize provider-side disconnect I/O without holding a DB transaction."""
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        _require_uuid(connection_id, "connection_id")
        lock_key = connection_operation_lock_key(connection_id)
        connection = self._engine.connect()
        locked = False
        try:
            try:
                with connection.begin():
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
                    _require_visible_connection(
                        connection,
                        installation_id=installation_id,
                        residence_id=residence_id,
                        connection_id=connection_id,
                    )

                connection.execute(select(func.pg_advisory_lock(lock_key)))
                connection.commit()
                locked = True
            except BankingPersistenceError:
                raise
            except DBAPIError:
                raise BankingPersistenceError(
                    "banking connection operation lock could not be acquired"
                ) from None

            yield
        finally:
            if locked:
                try:
                    unlocked = connection.scalar(
                        select(func.pg_advisory_unlock(lock_key))
                    )
                    connection.commit()
                    if unlocked is not True:
                        connection.invalidate()
                except DBAPIError:
                    connection.invalidate()
            connection.close()

    def prepare_connection_disconnection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        connection_id: UUID,
    ) -> BankingConnectionRecord:
        """Revalidate actor/scope and reject disconnect while sync is active."""
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
                status = _require_visible_connection(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    connection_id=connection_id,
                )
                _require_active_member(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )
                if status is not StoredConnectionStatus.DISCONNECTED:
                    _require_no_active_sync(
                        connection,
                        residence_id=residence_id,
                        connection_id=connection_id,
                    )
        except BankingPersistenceError:
            raise
        except DBAPIError:
            raise BankingPersistenceError(
                "banking connection could not be prepared for disconnection"
            ) from None

        reader = cast(_ConnectionReader, self)
        return reader.get_connection(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
        )

    def finalize_connection_disconnection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        connection_id: UUID,
    ) -> BankingConnectionRecord:
        """Atomically mark the local connection/accounts disconnected, preserving history."""
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
                status = _require_visible_connection(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    connection_id=connection_id,
                    for_update=True,
                )
                if status is not StoredConnectionStatus.DISCONNECTED:
                    _require_no_active_sync(
                        connection,
                        residence_id=residence_id,
                        connection_id=connection_id,
                    )
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
        except BankingPersistenceError:
            raise
        except DBAPIError:
            raise BankingPersistenceError(
                "banking connection could not be disconnected locally"
            ) from None

        reader = cast(_ConnectionReader, self)
        return reader.get_connection(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
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


def _require_visible_connection(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    connection_id: UUID,
    for_update: bool = False,
) -> StoredConnectionStatus:
    statement = select(connections.c.status).where(
        connections.c.id == connection_id,
        connections.c.installation_id == installation_id,
        connections.c.residence_id == residence_id,
    )
    if for_update:
        statement = statement.with_for_update()
    value = connection.scalar(statement)
    if value is None:
        raise ConnectionNotFoundError("banking connection was not found")
    return StoredConnectionStatus(value)


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
