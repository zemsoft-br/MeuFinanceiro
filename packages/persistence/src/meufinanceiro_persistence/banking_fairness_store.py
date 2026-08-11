"""Residence-scoped persistence for fair multi-run banking synchronization cycles."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, case, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.banking_fairness_models import (
    StoredSyncCycleStatus,
    SyncCycleAccountRecord,
    SyncCyclePlan,
    SyncCycleRecord,
)
from meufinanceiro_persistence.banking_fairness_schema import (
    sync_cycle_accounts,
    sync_cycles,
)
from meufinanceiro_persistence.banking_models import (
    BankingPersistenceError,
    ConnectionNotFoundError,
    StoredExternalAccountType,
    StoredSyncResource,
    SyncConflictError,
    clean_external_account_id,
)
from meufinanceiro_persistence.banking_sync_schema import (
    external_accounts,
    sync_cursors,
)
from meufinanceiro_persistence.schema import connections

_CYCLE_COLUMNS = (
    sync_cycles.c.id,
    sync_cycles.c.residence_id,
    sync_cycles.c.connection_id,
    sync_cycles.c.status,
    sync_cycles.c.started_at,
    sync_cycles.c.completed_at,
    sync_cycles.c.created_at,
    sync_cycles.c.updated_at,
)

_CYCLE_ACCOUNT_COLUMNS = (
    sync_cycle_accounts.c.id,
    sync_cycle_accounts.c.cycle_id,
    sync_cycle_accounts.c.residence_id,
    sync_cycle_accounts.c.connection_id,
    external_accounts.c.external_account_id.label("external_account_id"),
    sync_cycle_accounts.c.active_in_latest_snapshot,
    sync_cycle_accounts.c.pages_committed,
    sync_cycle_accounts.c.completed_at,
    sync_cycle_accounts.c.created_at,
    sync_cycle_accounts.c.updated_at,
)

_TRANSACTION_TYPES = {
    StoredExternalAccountType.BANK.value,
    StoredExternalAccountType.CREDIT.value,
}


class BankingSyncFairnessStoreMixin:
    """Track explicit full-scan cycles without interpreting provider cursors."""

    _engine: Engine

    def prepare_sync_cycle(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        eligible_external_account_ids: tuple[str, ...],
    ) -> SyncCyclePlan:
        normalized_ids = tuple(
            clean_external_account_id(value) for value in eligible_external_account_ids
        )
        if len(normalized_ids) != len(set(normalized_ids)):
            raise ValueError("eligible sync accounts contain duplicates")

        try:
            with self._engine.begin() as connection:
                _set_context(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                )
                _require_connection(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    connection_id=connection_id,
                )
                eligible_accounts = _eligible_accounts(
                    connection,
                    residence_id=residence_id,
                    connection_id=connection_id,
                    external_account_ids=normalized_ids,
                )
                cycle = _open_cycle(
                    connection,
                    residence_id=residence_id,
                    connection_id=connection_id,
                )
                if cycle is None:
                    has_previous_cycle = _has_completed_cycle(
                        connection,
                        residence_id=residence_id,
                        connection_id=connection_id,
                    )
                    cycle = _create_cycle(
                        connection,
                        residence_id=residence_id,
                        connection_id=connection_id,
                    )
                    if has_previous_cycle:
                        _clear_previous_cycle_cursors(
                            connection,
                            residence_id=residence_id,
                            connection_id=connection_id,
                            external_account_ids=normalized_ids,
                        )

                connection.execute(
                    update(sync_cycle_accounts)
                    .where(
                        sync_cycle_accounts.c.cycle_id == cycle["id"],
                        sync_cycle_accounts.c.residence_id == residence_id,
                        sync_cycle_accounts.c.connection_id == connection_id,
                        sync_cycle_accounts.c.active_in_latest_snapshot.is_(True),
                    )
                    .values(
                        active_in_latest_snapshot=False,
                        updated_at=func.transaction_timestamp(),
                    )
                )

                for account in eligible_accounts:
                    statement = postgresql_insert(sync_cycle_accounts).values(
                        id=uuid4(),
                        cycle_id=cycle["id"],
                        residence_id=residence_id,
                        connection_id=connection_id,
                        external_account_record_id=account["id"],
                        active_in_latest_snapshot=True,
                        pages_committed=0,
                        completed_at=None,
                        created_at=func.transaction_timestamp(),
                        updated_at=func.transaction_timestamp(),
                    )
                    connection.execute(
                        statement.on_conflict_do_update(
                            index_elements=[
                                sync_cycle_accounts.c.cycle_id,
                                sync_cycle_accounts.c.external_account_record_id,
                            ],
                            set_={
                                "active_in_latest_snapshot": True,
                                "updated_at": func.transaction_timestamp(),
                            },
                            where=(sync_cycle_accounts.c.residence_id == residence_id)
                            & (sync_cycle_accounts.c.connection_id == connection_id),
                        )
                    )

                pending_count = connection.scalar(
                    select(func.count())
                    .select_from(sync_cycle_accounts)
                    .where(
                        sync_cycle_accounts.c.cycle_id == cycle["id"],
                        sync_cycle_accounts.c.residence_id == residence_id,
                        sync_cycle_accounts.c.connection_id == connection_id,
                        sync_cycle_accounts.c.active_in_latest_snapshot.is_(True),
                        sync_cycle_accounts.c.completed_at.is_(None),
                    )
                )
                if pending_count == 0:
                    cycle = (
                        connection.execute(
                            update(sync_cycles)
                            .where(
                                sync_cycles.c.id == cycle["id"],
                                sync_cycles.c.residence_id == residence_id,
                                sync_cycles.c.connection_id == connection_id,
                                sync_cycles.c.status
                                == StoredSyncCycleStatus.OPEN.value,
                            )
                            .values(
                                status=StoredSyncCycleStatus.COMPLETED.value,
                                completed_at=func.transaction_timestamp(),
                                updated_at=func.transaction_timestamp(),
                            )
                            .returning(*_CYCLE_COLUMNS)
                        )
                        .mappings()
                        .one()
                    )

                account_rows = _active_cycle_accounts(
                    connection,
                    residence_id=residence_id,
                    connection_id=connection_id,
                    cycle_id=cycle["id"],
                )
        except BankingPersistenceError:
            raise
        except IntegrityError as error:
            if _sqlstate(error) == "23505":
                raise SyncConflictError(
                    "banking synchronization cycle conflicts with stored progress"
                ) from None
            raise BankingPersistenceError(
                "banking synchronization cycle could not be prepared"
            ) from None
        except DBAPIError:
            raise BankingPersistenceError(
                "banking synchronization cycle could not be prepared"
            ) from None

        return SyncCyclePlan(
            cycle=_cycle_record(cycle),
            accounts=tuple(_cycle_account_record(row) for row in account_rows),
        )


def _set_context(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
) -> None:
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


def _require_connection(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    connection_id: UUID,
) -> None:
    value = connection.scalar(
        select(connections.c.id)
        .where(
            connections.c.id == connection_id,
            connections.c.installation_id == installation_id,
            connections.c.residence_id == residence_id,
        )
        .with_for_update()
    )
    if value is None:
        raise ConnectionNotFoundError("banking connection was not found")


def _open_cycle(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
) -> RowMapping | None:
    return (
        connection.execute(
            select(*_CYCLE_COLUMNS)
            .where(
                sync_cycles.c.residence_id == residence_id,
                sync_cycles.c.connection_id == connection_id,
                sync_cycles.c.status == StoredSyncCycleStatus.OPEN.value,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )


def _has_completed_cycle(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
) -> bool:
    value = connection.scalar(
        select(sync_cycles.c.id)
        .where(
            sync_cycles.c.residence_id == residence_id,
            sync_cycles.c.connection_id == connection_id,
            sync_cycles.c.status == StoredSyncCycleStatus.COMPLETED.value,
        )
        .limit(1)
    )
    return value is not None


def _create_cycle(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
) -> RowMapping:
    return (
        connection.execute(
            sync_cycles.insert()
            .values(
                id=uuid4(),
                residence_id=residence_id,
                connection_id=connection_id,
                status=StoredSyncCycleStatus.OPEN.value,
                started_at=func.transaction_timestamp(),
                completed_at=None,
                created_at=func.transaction_timestamp(),
                updated_at=func.transaction_timestamp(),
            )
            .returning(*_CYCLE_COLUMNS)
        )
        .mappings()
        .one()
    )


def _eligible_accounts(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
    external_account_ids: tuple[str, ...],
) -> tuple[RowMapping, ...]:
    if not external_account_ids:
        return ()
    rows = (
        connection.execute(
            select(
                external_accounts.c.id,
                external_accounts.c.external_account_id,
                external_accounts.c.type,
            ).where(
                external_accounts.c.residence_id == residence_id,
                external_accounts.c.connection_id == connection_id,
                external_accounts.c.external_account_id.in_(external_account_ids),
            )
        )
        .mappings()
        .all()
    )
    if {row["external_account_id"] for row in rows} != set(external_account_ids):
        raise SyncConflictError("eligible banking account was not persisted")
    if any(row["type"] not in _TRANSACTION_TYPES for row in rows):
        raise SyncConflictError("banking account is not eligible for transaction sync")
    rows_by_external_id = {row["external_account_id"]: row for row in rows}
    return tuple(rows_by_external_id[account_id] for account_id in external_account_ids)


def _clear_previous_cycle_cursors(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
    external_account_ids: tuple[str, ...],
) -> None:
    if not external_account_ids:
        return
    connection.execute(
        delete(sync_cursors).where(
            sync_cursors.c.residence_id == residence_id,
            sync_cursors.c.connection_id == connection_id,
            sync_cursors.c.resource == StoredSyncResource.TRANSACTIONS.value,
            sync_cursors.c.external_account_id.in_(external_account_ids),
        )
    )


def _active_cycle_accounts(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
    cycle_id: UUID,
) -> tuple[RowMapping, ...]:
    cursor_priority = case((sync_cursors.c.id.is_not(None), 0), else_=1)
    return tuple(
        connection.execute(
            select(*_CYCLE_ACCOUNT_COLUMNS)
            .select_from(
                sync_cycle_accounts.join(
                    external_accounts,
                    (
                        sync_cycle_accounts.c.external_account_record_id
                        == external_accounts.c.id
                    )
                    & (
                        sync_cycle_accounts.c.connection_id
                        == external_accounts.c.connection_id
                    )
                    & (
                        sync_cycle_accounts.c.residence_id
                        == external_accounts.c.residence_id
                    ),
                ).outerjoin(
                    sync_cursors,
                    (sync_cursors.c.connection_id == external_accounts.c.connection_id)
                    & (sync_cursors.c.residence_id == external_accounts.c.residence_id)
                    & (
                        sync_cursors.c.external_account_id
                        == external_accounts.c.external_account_id
                    )
                    & (
                        sync_cursors.c.resource == StoredSyncResource.TRANSACTIONS.value
                    ),
                )
            )
            .where(
                sync_cycle_accounts.c.cycle_id == cycle_id,
                sync_cycle_accounts.c.residence_id == residence_id,
                sync_cycle_accounts.c.connection_id == connection_id,
                sync_cycle_accounts.c.active_in_latest_snapshot.is_(True),
            )
            .order_by(
                sync_cycle_accounts.c.pages_committed,
                cursor_priority,
                sync_cycle_accounts.c.created_at,
                sync_cycle_accounts.c.id,
            )
        )
        .mappings()
        .all()
    )


def _cycle_record(row: RowMapping) -> SyncCycleRecord:
    return SyncCycleRecord(
        id=row["id"],
        residence_id=row["residence_id"],
        connection_id=row["connection_id"],
        status=StoredSyncCycleStatus(row["status"]),
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _cycle_account_record(row: RowMapping) -> SyncCycleAccountRecord:
    return SyncCycleAccountRecord(
        id=row["id"],
        cycle_id=row["cycle_id"],
        residence_id=row["residence_id"],
        connection_id=row["connection_id"],
        external_account_id=row["external_account_id"],
        active_in_latest_snapshot=row["active_in_latest_snapshot"],
        pages_committed=row["pages_committed"],
        completed_at=row["completed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _sqlstate(error: DBAPIError) -> str | None:
    value = getattr(error.orig, "sqlstate", None)
    return value if isinstance(value, str) else None


__all__ = ["BankingSyncFairnessStoreMixin"]
