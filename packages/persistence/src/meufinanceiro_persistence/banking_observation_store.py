"""Atomic persistence of normalized transaction pages and their confirmed cursor."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, IntegrityError

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
        cursor: str,
        source_window: str,
        committed_at: datetime,
    ) -> AppliedTransactionPage:
        normalized_account_id = clean_external_account_id(external_account_id)
        normalized_cursor = clean_cursor(cursor)
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
        except BankingPersistenceError:
            raise
        except IntegrityError:
            raise SyncConflictError(
                "transaction observation identity conflicts with stored data"
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


def _commit_cursor(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
    external_account_id: str,
    cursor: str,
    source_window: str,
    committed_at: datetime,
) -> None:
    existing = (
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


__all__ = ["BankingTransactionObservationStoreMixin"]
