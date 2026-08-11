"""Residence-scoped persistence operations for bounded manual banking sync."""

from __future__ import annotations

from datetime import datetime
from typing import NoReturn
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.banking_models import (
    BankingPersistenceError,
    ConnectionNotFoundError,
    ExternalAccountNotFoundError,
    ExternalAccountRecord,
    ExternalAccountSnapshot,
    StoredConnectionStatus,
    StoredExternalAccountStatus,
    StoredExternalAccountType,
    StoredSyncErrorCategory,
    StoredSyncResource,
    StoredSyncStatus,
    StoredSyncTrigger,
    SyncConflictError,
    SyncCursorRecord,
    SyncRunNotFoundError,
    SyncRunRecord,
    SyncTransitionError,
    clean_cursor,
    clean_external_account_id,
    clean_http_status,
    clean_idempotency_key,
    clean_reason_code,
    clean_retry_window_bucket,
    clean_source_window,
    require_aware,
    validate_sync_completion,
)
from meufinanceiro_persistence.banking_sync_schema import (
    external_accounts,
    sync_cursors,
    sync_runs,
)
from meufinanceiro_persistence.schema import connections

_SYNC_RUN_COLUMNS = (
    sync_runs.c.id,
    sync_runs.c.residence_id,
    sync_runs.c.connection_id,
    sync_runs.c.idempotency_key,
    sync_runs.c.trigger,
    sync_runs.c.status,
    sync_runs.c.started_at,
    sync_runs.c.finished_at,
    sync_runs.c.attempt_count,
    sync_runs.c.error_category,
    sync_runs.c.provider_reason_code,
    sync_runs.c.http_status,
    sync_runs.c.retry_window_bucket,
    sync_runs.c.records_seen,
    sync_runs.c.records_applied,
    sync_runs.c.created_at,
    sync_runs.c.updated_at,
)

_EXTERNAL_ACCOUNT_COLUMNS = (
    external_accounts.c.id,
    external_accounts.c.residence_id,
    external_accounts.c.connection_id,
    external_accounts.c.external_account_id,
    external_accounts.c.type,
    external_accounts.c.subtype,
    external_accounts.c.currency,
    external_accounts.c.name,
    external_accounts.c.number_mask,
    external_accounts.c.status,
    external_accounts.c.first_seen_at,
    external_accounts.c.last_seen_at,
    external_accounts.c.updated_at,
)

_SYNC_CURSOR_COLUMNS = (
    sync_cursors.c.id,
    sync_cursors.c.residence_id,
    sync_cursors.c.connection_id,
    sync_cursors.c.external_account_id,
    sync_cursors.c.resource,
    sync_cursors.c.cursor,
    sync_cursors.c.source_window,
    sync_cursors.c.committed_at,
    sync_cursors.c.updated_at,
)


class BankingManualSyncStoreMixin:
    """Add provider-free manual-sync persistence to ``BankingIntegrationStore``."""

    _engine: Engine

    def begin_manual_sync(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        idempotency_key: str,
    ) -> SyncRunRecord:
        normalized_key = clean_idempotency_key(idempotency_key)
        try:
            with self._engine.begin() as connection:
                _set_context(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                )
                connection_status = _require_connection(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    connection_id=connection_id,
                    for_update=True,
                )
                existing = (
                    connection.execute(
                        select(*_SYNC_RUN_COLUMNS).where(
                            sync_runs.c.residence_id == residence_id,
                            sync_runs.c.connection_id == connection_id,
                            sync_runs.c.idempotency_key == normalized_key,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    return _sync_run_record(existing)
                if connection_status is StoredConnectionStatus.DISCONNECTED:
                    raise SyncConflictError(
                        "disconnected banking connection cannot be synchronized"
                    )

                try:
                    row = (
                        connection.execute(
                            sync_runs.insert()
                            .values(
                                id=uuid4(),
                                residence_id=residence_id,
                                connection_id=connection_id,
                                idempotency_key=normalized_key,
                                trigger=StoredSyncTrigger.MANUAL.value,
                                status=StoredSyncStatus.REQUESTED.value,
                                started_at=None,
                                finished_at=None,
                                attempt_count=0,
                                error_category=None,
                                provider_reason_code=None,
                                http_status=None,
                                retry_window_bucket=None,
                                records_seen=0,
                                records_applied=0,
                                created_at=func.transaction_timestamp(),
                                updated_at=func.transaction_timestamp(),
                            )
                            .returning(*_SYNC_RUN_COLUMNS)
                        )
                        .mappings()
                        .one()
                    )
                except IntegrityError as error:
                    if _sqlstate(error) == "23505":
                        raise SyncConflictError(
                            "banking synchronization is already active"
                        ) from None
                    raise
        except BankingPersistenceError:
            raise
        except DBAPIError:
            raise BankingPersistenceError(
                "banking synchronization could not be started"
            ) from None
        return _sync_run_record(row)

    def mark_sync_running(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        sync_run_id: UUID,
    ) -> SyncRunRecord:
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
                row = (
                    connection.execute(
                        update(sync_runs)
                        .where(
                            sync_runs.c.id == sync_run_id,
                            sync_runs.c.residence_id == residence_id,
                            sync_runs.c.connection_id == connection_id,
                            sync_runs.c.status == StoredSyncStatus.REQUESTED.value,
                        )
                        .values(
                            status=StoredSyncStatus.RUNNING.value,
                            started_at=func.transaction_timestamp(),
                            attempt_count=sync_runs.c.attempt_count + 1,
                            updated_at=func.transaction_timestamp(),
                        )
                        .returning(*_SYNC_RUN_COLUMNS)
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    _raise_sync_run_write_error(
                        connection,
                        residence_id=residence_id,
                        connection_id=connection_id,
                        sync_run_id=sync_run_id,
                    )
        except BankingPersistenceError:
            raise
        except DBAPIError:
            raise BankingPersistenceError(
                "banking synchronization could not be updated"
            ) from None
        return _sync_run_record(row)

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
    ) -> SyncRunRecord:
        validate_sync_completion(
            status=status,
            error_category=error_category,
            provider_reason_code=provider_reason_code,
            http_status=http_status,
            retry_window_bucket=retry_window_bucket,
            records_seen=records_seen,
            records_applied=records_applied,
        )
        normalized_reason = clean_reason_code(provider_reason_code)
        normalized_http_status = clean_http_status(http_status)
        normalized_retry_bucket = clean_retry_window_bucket(retry_window_bucket)
        allowed_sources = (
            (StoredSyncStatus.RUNNING.value,)
            if status in {StoredSyncStatus.PARTIAL, StoredSyncStatus.SUCCEEDED}
            else (StoredSyncStatus.REQUESTED.value, StoredSyncStatus.RUNNING.value)
        )

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
                row = (
                    connection.execute(
                        update(sync_runs)
                        .where(
                            sync_runs.c.id == sync_run_id,
                            sync_runs.c.residence_id == residence_id,
                            sync_runs.c.connection_id == connection_id,
                            sync_runs.c.status.in_(allowed_sources),
                        )
                        .values(
                            status=status.value,
                            finished_at=func.transaction_timestamp(),
                            error_category=(
                                error_category.value
                                if error_category is not None
                                else None
                            ),
                            provider_reason_code=normalized_reason,
                            http_status=normalized_http_status,
                            retry_window_bucket=normalized_retry_bucket,
                            records_seen=records_seen,
                            records_applied=records_applied,
                            updated_at=func.transaction_timestamp(),
                        )
                        .returning(*_SYNC_RUN_COLUMNS)
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    _raise_sync_run_write_error(
                        connection,
                        residence_id=residence_id,
                        connection_id=connection_id,
                        sync_run_id=sync_run_id,
                    )
        except BankingPersistenceError:
            raise
        except DBAPIError:
            raise BankingPersistenceError(
                "banking synchronization could not be completed"
            ) from None
        return _sync_run_record(row)

    def replace_external_accounts(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        snapshots: tuple[ExternalAccountSnapshot, ...],
    ) -> tuple[ExternalAccountRecord, ...]:
        normalized = tuple(snapshots)
        external_ids = [snapshot.external_account_id for snapshot in normalized]
        if len(external_ids) != len(set(external_ids)):
            raise ValueError("external account snapshot contains duplicates")

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

                for snapshot in normalized:
                    statement = postgresql_insert(external_accounts).values(
                        id=uuid4(),
                        residence_id=residence_id,
                        connection_id=connection_id,
                        external_account_id=snapshot.external_account_id,
                        type=snapshot.account_type.value,
                        subtype=snapshot.subtype,
                        currency=snapshot.currency,
                        name=snapshot.name,
                        number_mask=snapshot.number_mask,
                        status=snapshot.status.value,
                        first_seen_at=snapshot.observed_at,
                        last_seen_at=snapshot.observed_at,
                        updated_at=func.transaction_timestamp(),
                    )
                    connection.execute(
                        statement.on_conflict_do_update(
                            index_elements=[
                                external_accounts.c.connection_id,
                                external_accounts.c.external_account_id,
                            ],
                            set_={
                                "type": snapshot.account_type.value,
                                "subtype": snapshot.subtype,
                                "currency": snapshot.currency,
                                "name": snapshot.name,
                                "number_mask": snapshot.number_mask,
                                "status": snapshot.status.value,
                                "last_seen_at": snapshot.observed_at,
                                "updated_at": func.transaction_timestamp(),
                            },
                            where=(external_accounts.c.residence_id == residence_id)
                            & (
                                external_accounts.c.last_seen_at <= snapshot.observed_at
                            ),
                        )
                    )

                rows = (
                    connection.execute(
                        select(*_EXTERNAL_ACCOUNT_COLUMNS)
                        .where(
                            external_accounts.c.residence_id == residence_id,
                            external_accounts.c.connection_id == connection_id,
                        )
                        .order_by(external_accounts.c.id)
                    )
                    .mappings()
                    .all()
                )
        except BankingPersistenceError:
            raise
        except DBAPIError:
            raise BankingPersistenceError(
                "external banking accounts could not be persisted"
            ) from None
        return tuple(_external_account_record(row) for row in rows)

    def get_sync_cursor(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        external_account_id: str,
        resource: StoredSyncResource = StoredSyncResource.TRANSACTIONS,
    ) -> SyncCursorRecord | None:
        normalized_account_id = clean_external_account_id(external_account_id)
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
                _require_external_account(
                    connection,
                    residence_id=residence_id,
                    connection_id=connection_id,
                    external_account_id=normalized_account_id,
                )
                row = (
                    connection.execute(
                        select(*_SYNC_CURSOR_COLUMNS).where(
                            sync_cursors.c.residence_id == residence_id,
                            sync_cursors.c.connection_id == connection_id,
                            sync_cursors.c.external_account_id == normalized_account_id,
                            sync_cursors.c.resource == resource.value,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except BankingPersistenceError:
            raise
        except DBAPIError:
            raise BankingPersistenceError(
                "banking sync cursor could not be read"
            ) from None
        return None if row is None else _sync_cursor_record(row)

    def commit_sync_cursor(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        external_account_id: str,
        cursor: str,
        source_window: str,
        committed_at: datetime,
        resource: StoredSyncResource = StoredSyncResource.TRANSACTIONS,
    ) -> SyncCursorRecord:
        normalized_account_id = clean_external_account_id(external_account_id)
        normalized_cursor = clean_cursor(cursor)
        normalized_window = clean_source_window(source_window)
        require_aware(committed_at, "committed_at")

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
                _require_external_account(
                    connection,
                    residence_id=residence_id,
                    connection_id=connection_id,
                    external_account_id=normalized_account_id,
                )
                existing = (
                    connection.execute(
                        select(*_SYNC_CURSOR_COLUMNS)
                        .where(
                            sync_cursors.c.residence_id == residence_id,
                            sync_cursors.c.connection_id == connection_id,
                            sync_cursors.c.external_account_id == normalized_account_id,
                            sync_cursors.c.resource == resource.value,
                        )
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if existing["committed_at"] > committed_at:
                        raise SyncConflictError("banking sync cursor commit is stale")
                    if existing["committed_at"] == committed_at:
                        if (
                            existing["cursor"] == normalized_cursor
                            and existing["source_window"] == normalized_window
                        ):
                            return _sync_cursor_record(existing)
                        raise SyncConflictError(
                            "banking sync cursor commit is inconsistent"
                        )
                    row = (
                        connection.execute(
                            update(sync_cursors)
                            .where(sync_cursors.c.id == existing["id"])
                            .values(
                                cursor=normalized_cursor,
                                source_window=normalized_window,
                                committed_at=committed_at,
                                updated_at=func.transaction_timestamp(),
                            )
                            .returning(*_SYNC_CURSOR_COLUMNS)
                        )
                        .mappings()
                        .one()
                    )
                else:
                    row = (
                        connection.execute(
                            sync_cursors.insert()
                            .values(
                                id=uuid4(),
                                residence_id=residence_id,
                                connection_id=connection_id,
                                external_account_id=normalized_account_id,
                                resource=resource.value,
                                cursor=normalized_cursor,
                                source_window=normalized_window,
                                committed_at=committed_at,
                                updated_at=func.transaction_timestamp(),
                            )
                            .returning(*_SYNC_CURSOR_COLUMNS)
                        )
                        .mappings()
                        .one()
                    )
        except BankingPersistenceError:
            raise
        except DBAPIError:
            raise BankingPersistenceError(
                "banking sync cursor could not be persisted"
            ) from None
        return _sync_cursor_record(row)


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


def _require_external_account(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
    external_account_id: str,
) -> None:
    value = connection.scalar(
        select(external_accounts.c.id).where(
            external_accounts.c.residence_id == residence_id,
            external_accounts.c.connection_id == connection_id,
            external_accounts.c.external_account_id == external_account_id,
        )
    )
    if value is None:
        raise ExternalAccountNotFoundError("external banking account was not found")


def _raise_sync_run_write_error(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
    sync_run_id: UUID,
) -> NoReturn:
    status = connection.scalar(
        select(sync_runs.c.status).where(
            sync_runs.c.id == sync_run_id,
            sync_runs.c.residence_id == residence_id,
            sync_runs.c.connection_id == connection_id,
        )
    )
    if status is None:
        raise SyncRunNotFoundError("banking synchronization was not found")
    raise SyncTransitionError("banking synchronization transition is invalid")


def _sqlstate(error: DBAPIError) -> str | None:
    value = getattr(error.orig, "sqlstate", None)
    return value if isinstance(value, str) else None


def _sync_run_record(row: RowMapping) -> SyncRunRecord:
    error_category = row["error_category"]
    return SyncRunRecord(
        id=row["id"],
        residence_id=row["residence_id"],
        connection_id=row["connection_id"],
        idempotency_key=row["idempotency_key"],
        trigger=StoredSyncTrigger(row["trigger"]),
        status=StoredSyncStatus(row["status"]),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        attempt_count=row["attempt_count"],
        error_category=(
            StoredSyncErrorCategory(error_category)
            if error_category is not None
            else None
        ),
        provider_reason_code=row["provider_reason_code"],
        http_status=row["http_status"],
        retry_window_bucket=row["retry_window_bucket"],
        records_seen=row["records_seen"],
        records_applied=row["records_applied"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _external_account_record(row: RowMapping) -> ExternalAccountRecord:
    return ExternalAccountRecord(
        id=row["id"],
        residence_id=row["residence_id"],
        connection_id=row["connection_id"],
        external_account_id=row["external_account_id"],
        account_type=StoredExternalAccountType(row["type"]),
        subtype=row["subtype"],
        currency=row["currency"],
        name=row["name"],
        number_mask=row["number_mask"],
        status=StoredExternalAccountStatus(row["status"]),
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        updated_at=row["updated_at"],
    )


def _sync_cursor_record(row: RowMapping) -> SyncCursorRecord:
    return SyncCursorRecord(
        id=row["id"],
        residence_id=row["residence_id"],
        connection_id=row["connection_id"],
        external_account_id=row["external_account_id"],
        resource=StoredSyncResource(row["resource"]),
        cursor=row["cursor"],
        source_window=row["source_window"],
        committed_at=row["committed_at"],
        updated_at=row["updated_at"],
    )
