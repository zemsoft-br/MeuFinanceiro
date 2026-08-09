"""Atomic persistence of normalized transaction pages and confirmed sync progress."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.banking_fairness_models import StoredSyncCycleStatus
from meufinanceiro_persistence.banking_fairness_schema import (
    sync_cycle_accounts,
    sync_cycles,
)
from meufinanceiro_persistence.banking_models import (
    BankingPersistenceError,
    ConnectionNotFoundError,
    ExternalAccountNotFoundError,
    StoredSyncResource,
    SyncConflictError,
    clean_cursor,
    clean_external_account_id,
    clean_source_window,
    require_aware,
)
from meufinanceiro_persistence.banking_observation_models import (
    AppliedTransactionPage,
    TransactionObservationSnapshot,
)
from meufinanceiro_persistence.banking_observation_schema import external_observations
from meufinanceiro_persistence.schema import connections, external_accounts, sync_cursors


class BankingTransactionObservationStoreMixin:
    """Provider-free atomic transaction-page persistence."""

    _engine: Engine

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
    ) -> AppliedTransactionPage:
        normalized_account_id = clean_external_account_id(external_account_id)
        normalized_cursor = None if cursor is None else clean_cursor(cursor)
        normalized_window = clean_source_window(source_window)
        require_aware(committed_at, "committed_at")

        normalized_observations = tuple(observations)
        fingerprints: list[str] = []
        for observation in normalized_observations:
            if not isinstance(observation, TransactionObservationSnapshot):
                raise TypeError(
                    "observations must contain TransactionObservationSnapshot"
                )
            if observation.external_account_id != normalized_account_id:
                raise ValueError("transaction observation belongs to another account")
            if observation.observed_at > committed_at:
                raise ValueError(
                    "transaction observation cannot be newer than the page commit"
                )
            fingerprints.append(observation.stable_fingerprint)
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError("transaction page contains duplicate observations")

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
                _lock_external_account(
                    connection,
                    residence_id=residence_id,
                    connection_id=connection_id,
                    external_account_id=normalized_account_id,
                )
                cycle_account_id: UUID | None = None
                if sync_cycle_id is not None:
                    cycle_account_id = _require_cycle_progress(
                        connection,
                        residence_id=residence_id,
                        connection_id=connection_id,
                        external_account_id=normalized_account_id,
                        sync_cycle_id=sync_cycle_id,
                    )
                if _page_cursor_already_committed(
                    connection,
                    residence_id=residence_id,
                    connection_id=connection_id,
                    external_account_id=normalized_account_id,
                    cursor=normalized_cursor,
                    source_window=normalized_window,
                    committed_at=committed_at,
                ):
                    return AppliedTransactionPage(
                        records_seen=len(normalized_observations),
                        records_applied=0,
                        committed_at=committed_at,
                    )

                records_applied = 0
                for observation in normalized_observations:
                    statement = postgresql_insert(external_observations).values(
                        id=uuid4(),
                        residence_id=residence_id,
                        connection_id=connection_id,
                        external_account_id=normalized_account_id,
                        resource_type="transactions",
                        external_resource_id=observation.external_resource_id,
                        status=observation.status.value,
                        provider_updated_at=observation.provider_updated_at,
                        effective_date=observation.effective_date,
                        amount=observation.amount,
                        currency=observation.currency,
                        description=observation.description,
                        category=observation.category,
                        stable_fingerprint=observation.stable_fingerprint,
                        first_seen_at=observation.observed_at,
                        last_seen_at=observation.observed_at,
                        deleted_at=observation.deleted_at,
                        normalized_payload_version=(
                            observation.normalized_payload_version
                        ),
                        updated_at=func.transaction_timestamp(),
                    )
                    result = connection.execute(
                        statement.on_conflict_do_update(
                            index_elements=[
                                external_observations.c.connection_id,
                                external_observations.c.external_account_id,
                                external_observations.c.stable_fingerprint,
                            ],
                            set_={
                                "external_resource_id": (
                                    observation.external_resource_id
                                ),
                                "status": observation.status.value,
                                "provider_updated_at": (
                                    observation.provider_updated_at
                                ),
                                "effective_date": observation.effective_date,
                                "amount": observation.amount,
                                "currency": observation.currency,
                                "description": observation.description,
                                "category": observation.category,
                                "last_seen_at": observation.observed_at,
                                "deleted_at": observation.deleted_at,
                                "normalized_payload_version": (
                                    observation.normalized_payload_version
                                ),
                                "updated_at": func.transaction_timestamp(),
                            },
                            where=(
                                external_observations.c.residence_id
                                == residence_id
                            )
                            & (
                                external_observations.c.last_seen_at
                                < observation.observed_at
                            ),
                        )
                    )
                    if result.rowcount and result.rowcount > 0:
                        records_applied += 1

                _commit_cursor(
                    connection,
                    residence_id=residence_id,
                    connection_id=connection_id,
                    external_account_id=normalized_account_id,
                    cursor=normalized_cursor,
                    source_window=normalized_window,
                    committed_at=committed_at,
                )
                if cycle_account_id is not None and sync_cycle_id is not None:
                    _advance_cycle_account(
                        connection,
                        residence_id=residence_id,
                        connection_id=connection_id,
                        cycle_account_id=cycle_account_id,
                        sync_cycle_id=sync_cycle_id,
                        terminal=normalized_cursor is None,
                    )
        except BankingPersistenceError:
            raise
        except IntegrityError as error:
            if _sqlstate(error) == "23505":
                raise SyncConflictError(
                    "transaction observation identity conflicts with stored data"
                ) from None
            raise BankingPersistenceError(
                "transaction observation page could not be persisted"
            ) from None
        except DBAPIError:
            raise BankingPersistenceError(
                "transaction observation page could not be persisted"
            ) from None

        return AppliedTransactionPage(
            records_seen=len(normalized_observations),
            records_applied=records_applied,
            committed_at=committed_at,
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
        select(connections.c.id).where(
            connections.c.id == connection_id,
            connections.c.installation_id == installation_id,
            connections.c.residence_id == residence_id,
        )
    )
    if value is None:
        raise ConnectionNotFoundError("banking connection was not found")


def _lock_external_account(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
    external_account_id: str,
) -> None:
    value = connection.scalar(
        select(external_accounts.c.id)
        .where(
            external_accounts.c.residence_id == residence_id,
            external_accounts.c.connection_id == connection_id,
            external_accounts.c.external_account_id == external_account_id,
        )
        .with_for_update()
    )
    if value is None:
        raise ExternalAccountNotFoundError("external banking account was not found")


def _require_cycle_progress(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
    external_account_id: str,
    sync_cycle_id: UUID,
) -> UUID:
    row = (
        connection.execute(
            select(
                sync_cycle_accounts.c.id,
                sync_cycles.c.status,
                sync_cycle_accounts.c.active_in_latest_snapshot,
                sync_cycle_accounts.c.completed_at,
            )
            .select_from(
                sync_cycle_accounts.join(
                    sync_cycles,
                    (sync_cycle_accounts.c.cycle_id == sync_cycles.c.id)
                    & (
                        sync_cycle_accounts.c.connection_id
                        == sync_cycles.c.connection_id
                    )
                    & (
                        sync_cycle_accounts.c.residence_id
                        == sync_cycles.c.residence_id
                    ),
                ).join(
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
                )
            )
            .where(
                sync_cycle_accounts.c.cycle_id == sync_cycle_id,
                sync_cycle_accounts.c.residence_id == residence_id,
                sync_cycle_accounts.c.connection_id == connection_id,
                external_accounts.c.external_account_id == external_account_id,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise SyncConflictError("banking sync cycle account was not found")
    if not row["active_in_latest_snapshot"]:
        raise SyncConflictError("banking sync cycle account is not active")

    cycle_account_id = row["id"]
    if not isinstance(cycle_account_id, UUID):
        raise SyncConflictError("banking sync cycle account identity is invalid")
    if (
        row["status"] == StoredSyncCycleStatus.COMPLETED.value
        or row["completed_at"] is not None
    ):
        raise SyncConflictError("banking sync cycle account is already completed")
    return cycle_account_id


def _advance_cycle_account(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
    cycle_account_id: UUID,
    sync_cycle_id: UUID,
    terminal: bool,
) -> None:
    statement = update(sync_cycle_accounts).where(
        sync_cycle_accounts.c.id == cycle_account_id,
        sync_cycle_accounts.c.cycle_id == sync_cycle_id,
        sync_cycle_accounts.c.residence_id == residence_id,
        sync_cycle_accounts.c.connection_id == connection_id,
        sync_cycle_accounts.c.active_in_latest_snapshot.is_(True),
        sync_cycle_accounts.c.completed_at.is_(None),
    )
    if terminal:
        statement = statement.values(
            pages_committed=sync_cycle_accounts.c.pages_committed + 1,
            completed_at=func.transaction_timestamp(),
            updated_at=func.transaction_timestamp(),
        )
    else:
        statement = statement.values(
            pages_committed=sync_cycle_accounts.c.pages_committed + 1,
            updated_at=func.transaction_timestamp(),
        )

    advanced_id = connection.scalar(statement.returning(sync_cycle_accounts.c.id))
    if advanced_id != cycle_account_id:
        raise SyncConflictError("banking sync cycle progress is inconsistent")

    if not terminal:
        return

    pending_count = connection.scalar(
        select(func.count())
        .select_from(sync_cycle_accounts)
        .where(
            sync_cycle_accounts.c.cycle_id == sync_cycle_id,
            sync_cycle_accounts.c.residence_id == residence_id,
            sync_cycle_accounts.c.connection_id == connection_id,
            sync_cycle_accounts.c.active_in_latest_snapshot.is_(True),
            sync_cycle_accounts.c.completed_at.is_(None),
        )
    )
    if pending_count == 0:
        cycle_id = connection.scalar(
            update(sync_cycles)
            .where(
                sync_cycles.c.id == sync_cycle_id,
                sync_cycles.c.residence_id == residence_id,
                sync_cycles.c.connection_id == connection_id,
                sync_cycles.c.status == StoredSyncCycleStatus.OPEN.value,
            )
            .values(
                status=StoredSyncCycleStatus.COMPLETED.value,
                completed_at=func.transaction_timestamp(),
                updated_at=func.transaction_timestamp(),
            )
            .returning(sync_cycles.c.id)
        )
        if cycle_id != sync_cycle_id:
            raise SyncConflictError("banking sync cycle completion is inconsistent")


def _page_cursor_already_committed(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
    external_account_id: str,
    cursor: str | None,
    source_window: str,
    committed_at: datetime,
) -> bool:
    existing = _locked_cursor(
        connection,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=external_account_id,
    )
    if existing is None:
        return False
    previous_committed_at = existing["committed_at"]
    if previous_committed_at > committed_at:
        raise SyncConflictError("banking sync cursor commit is stale")
    if previous_committed_at < committed_at:
        return False
    if cursor is not None and (
        existing["cursor"] == cursor and existing["source_window"] == source_window
    ):
        return True
    raise SyncConflictError("banking sync cursor commit is inconsistent")


def _commit_cursor(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
    external_account_id: str,
    cursor: str | None,
    source_window: str,
    committed_at: datetime,
) -> None:
    existing = _locked_cursor(
        connection,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=external_account_id,
    )
    if cursor is None:
        if existing is None:
            return
        previous_committed_at = existing["committed_at"]
        if previous_committed_at >= committed_at:
            raise SyncConflictError("banking sync cursor commit is inconsistent")
        connection.execute(delete(sync_cursors).where(sync_cursors.c.id == existing["id"]))
        return

    if existing is None:
        connection.execute(
            sync_cursors.insert().values(
                id=uuid4(),
                residence_id=residence_id,
                connection_id=connection_id,
                external_account_id=external_account_id,
                resource=StoredSyncResource.TRANSACTIONS.value,
                cursor=cursor,
                source_window=source_window,
                committed_at=committed_at,
                updated_at=func.transaction_timestamp(),
            )
        )
        return

    previous_committed_at = existing["committed_at"]
    if previous_committed_at > committed_at:
        raise SyncConflictError("banking sync cursor commit is stale")
    if previous_committed_at == committed_at:
        if existing["cursor"] == cursor and existing["source_window"] == source_window:
            return
        raise SyncConflictError("banking sync cursor commit is inconsistent")

    connection.execute(
        update(sync_cursors)
        .where(sync_cursors.c.id == existing["id"])
        .values(
            cursor=cursor,
            source_window=source_window,
            committed_at=committed_at,
            updated_at=func.transaction_timestamp(),
        )
    )


def _locked_cursor(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
    external_account_id: str,
) -> RowMapping | None:
    return (
        connection.execute(
            select(
                sync_cursors.c.id,
                sync_cursors.c.cursor,
                sync_cursors.c.source_window,
                sync_cursors.c.committed_at,
            )
            .where(
                sync_cursors.c.residence_id == residence_id,
                sync_cursors.c.connection_id == connection_id,
                sync_cursors.c.external_account_id == external_account_id,
                sync_cursors.c.resource == StoredSyncResource.TRANSACTIONS.value,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )


def _sqlstate(error: DBAPIError) -> str | None:
    value = getattr(error.orig, "sqlstate", None)
    return value if isinstance(value, str) else None


__all__ = ["BankingTransactionObservationStoreMixin"]
