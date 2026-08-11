"""Bounded provider-neutral reconciliation of normalized transaction observations."""

from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, or_, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.banking_models import ConnectionNotFoundError
from meufinanceiro_persistence.banking_observation_models import (
    StoredTransactionObservationStatus,
)
from meufinanceiro_persistence.banking_observation_schema import external_observations
from meufinanceiro_persistence.banking_reconciliation_models import (
    ReconciledTransactionIdentityKind,
    TransactionReconciliationConflictError,
    TransactionReconciliationError,
    TransactionReconciliationResult,
)
from meufinanceiro_persistence.banking_reconciliation_schema import (
    reconciled_transaction_sources,
    reconciled_transactions,
)
from meufinanceiro_persistence.schema import connections, external_accounts

_RECONCILIATION_IDENTITY_NAMESPACE = "meufinanceiro:reconciled-transaction:v1"
_DEFAULT_RECONCILIATION_LIMIT = 500
_MAX_RECONCILIATION_LIMIT = 1_000


class BankingTransactionReconciliationStoreMixin:
    """Materialize deterministic local transaction state without provider I/O."""

    _engine: Engine

    def reconcile_transaction_observations(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        limit: int = _DEFAULT_RECONCILIATION_LIMIT,
    ) -> TransactionReconciliationResult:
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(connection_id, "connection_id")
        normalized_limit = _clean_limit(limit)

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
                rows = _dirty_observations(
                    connection,
                    residence_id=residence_id,
                    connection_id=connection_id,
                    limit=normalized_limit + 1,
                )
                has_more = len(rows) > normalized_limit
                selected = rows[:normalized_limit]

                created = 0
                updated = 0
                unchanged = 0
                for row in selected:
                    action = _reconcile_observation(
                        connection,
                        residence_id=residence_id,
                        connection_id=connection_id,
                        observation=row,
                    )
                    if action == "created":
                        created += 1
                    elif action == "updated":
                        updated += 1
                    elif action == "unchanged":
                        unchanged += 1
                    else:  # pragma: no cover - internal invariant
                        raise TransactionReconciliationError(
                            "transaction reconciliation produced an invalid action"
                        )
        except (ConnectionNotFoundError, TransactionReconciliationError):
            raise
        except IntegrityError as error:
            if _sqlstate(error) == "23505":
                raise TransactionReconciliationConflictError(
                    "transaction reconciliation identity conflicts with stored state"
                ) from None
            raise TransactionReconciliationError(
                "transaction reconciliation could not be persisted"
            ) from None
        except DBAPIError:
            raise TransactionReconciliationError(
                "transaction reconciliation could not be persisted"
            ) from None

        return TransactionReconciliationResult(
            observations_seen=len(selected),
            identities_created=created,
            identities_updated=updated,
            identities_unchanged=unchanged,
            has_more=has_more,
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
            ),
            func.set_config(
                "app.current_residence_id",
                str(residence_id),
                True,
            ),
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


def _dirty_observations(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
    limit: int,
) -> tuple[RowMapping, ...]:
    source = reconciled_transaction_sources
    observation_account_join = (
        (external_observations.c.connection_id == external_accounts.c.connection_id)
        & (external_observations.c.residence_id == external_accounts.c.residence_id)
        & (
            external_observations.c.external_account_id
            == external_accounts.c.external_account_id
        )
    )
    source_join = (
        (source.c.source_observation_id == external_observations.c.id)
        & (source.c.connection_id == external_observations.c.connection_id)
        & (source.c.residence_id == external_observations.c.residence_id)
    )
    statement = (
        select(
            external_observations.c.id.label("observation_id"),
            external_accounts.c.id.label("external_account_record_id"),
            external_observations.c.external_resource_id,
            external_observations.c.stable_fingerprint,
            external_observations.c.status,
            external_observations.c.last_seen_at,
            external_observations.c.updated_at.label("observation_updated_at"),
        )
        .select_from(
            external_observations.join(
                external_accounts,
                observation_account_join,
            ).outerjoin(source, source_join)
        )
        .where(
            external_observations.c.residence_id == residence_id,
            external_observations.c.connection_id == connection_id,
            external_observations.c.resource_type == "transactions",
            or_(
                source.c.id.is_(None),
                source.c.observation_updated_at != external_observations.c.updated_at,
            ),
        )
        .order_by(
            external_observations.c.updated_at,
            external_observations.c.id,
        )
        .limit(limit)
        .with_for_update(of=external_observations)
    )
    return tuple(connection.execute(statement).mappings().all())


def _reconcile_observation(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
    observation: RowMapping,
) -> str:
    observation_id = _uuid_value(observation["observation_id"], "observation_id")
    account_record_id = _uuid_value(
        observation["external_account_record_id"],
        "external_account_record_id",
    )
    observation_updated_at = _aware_datetime(
        observation["observation_updated_at"],
        "observation_updated_at",
    )
    observed_at = _aware_datetime(observation["last_seen_at"], "last_seen_at")

    source_progress = _locked_source_progress(
        connection,
        residence_id=residence_id,
        connection_id=connection_id,
        observation_id=observation_id,
    )
    if source_progress is not None:
        source_updated_at = _aware_datetime(
            source_progress["observation_updated_at"],
            "source observation_updated_at",
        )
        if source_updated_at > observation_updated_at:
            raise TransactionReconciliationConflictError(
                "transaction reconciliation source progress is ahead of observation state"
            )
        if source_updated_at == observation_updated_at:
            return "unchanged"

    status = _stored_status(observation["status"])
    identity_kind, identity_digest = _identity(
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_record_id=account_record_id,
        external_resource_id=observation["external_resource_id"],
        stable_fingerprint=observation["stable_fingerprint"],
    )
    target = _locked_target(
        connection,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_record_id=account_record_id,
        identity_kind=identity_kind,
        identity_digest=identity_digest,
    )

    action: str
    if target is None:
        if source_progress is not None:
            raise TransactionReconciliationConflictError(
                "transaction reconciliation source points to missing canonical state"
            )
        target_id = uuid4()
        connection.execute(
            reconciled_transactions.insert().values(
                id=target_id,
                residence_id=residence_id,
                connection_id=connection_id,
                external_account_record_id=account_record_id,
                identity_kind=identity_kind.value,
                identity_digest=identity_digest,
                status=status.value,
                source_observation_id=observation_id,
                source_observed_at=observed_at,
                first_reconciled_at=func.transaction_timestamp(),
                updated_at=func.transaction_timestamp(),
            )
        )
        action = "created"
    else:
        target_id = _uuid_value(target["id"], "reconciled transaction id")
        if source_progress is not None and (
            source_progress["reconciled_transaction_id"] != target_id
        ):
            raise TransactionReconciliationConflictError(
                "transaction reconciliation source points to another canonical identity"
            )

        current_observed_at = _aware_datetime(
            target["source_observed_at"],
            "canonical source_observed_at",
        )
        if current_observed_at > observed_at:
            action = "unchanged"
        elif current_observed_at == observed_at:
            if (
                target["source_observation_id"] != observation_id
                or target["status"] != status.value
            ):
                raise TransactionReconciliationConflictError(
                    "transaction reconciliation has incompatible observations at the same time"
                )
            action = "unchanged"
        else:
            updated_id = connection.scalar(
                update(reconciled_transactions)
                .where(
                    reconciled_transactions.c.id == target_id,
                    reconciled_transactions.c.residence_id == residence_id,
                    reconciled_transactions.c.connection_id == connection_id,
                    reconciled_transactions.c.source_observed_at == current_observed_at,
                )
                .values(
                    status=status.value,
                    source_observation_id=observation_id,
                    source_observed_at=observed_at,
                    updated_at=func.transaction_timestamp(),
                )
                .returning(reconciled_transactions.c.id)
            )
            if updated_id != target_id:
                raise TransactionReconciliationConflictError(
                    "transaction reconciliation canonical state changed concurrently"
                )
            action = "updated"

    _record_source_progress(
        connection,
        residence_id=residence_id,
        connection_id=connection_id,
        reconciled_transaction_id=target_id,
        observation_id=observation_id,
        observation_updated_at=observation_updated_at,
        existing=source_progress,
    )
    return action


def _locked_source_progress(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
    observation_id: UUID,
) -> RowMapping | None:
    return (
        connection.execute(
            select(
                reconciled_transaction_sources.c.id,
                reconciled_transaction_sources.c.reconciled_transaction_id,
                reconciled_transaction_sources.c.observation_updated_at,
            )
            .where(
                reconciled_transaction_sources.c.source_observation_id
                == observation_id,
                reconciled_transaction_sources.c.residence_id == residence_id,
                reconciled_transaction_sources.c.connection_id == connection_id,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )


def _locked_target(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
    external_account_record_id: UUID,
    identity_kind: ReconciledTransactionIdentityKind,
    identity_digest: str,
) -> RowMapping | None:
    return (
        connection.execute(
            select(
                reconciled_transactions.c.id,
                reconciled_transactions.c.status,
                reconciled_transactions.c.source_observation_id,
                reconciled_transactions.c.source_observed_at,
            )
            .where(
                reconciled_transactions.c.residence_id == residence_id,
                reconciled_transactions.c.connection_id == connection_id,
                reconciled_transactions.c.external_account_record_id
                == external_account_record_id,
                reconciled_transactions.c.identity_kind == identity_kind.value,
                reconciled_transactions.c.identity_digest == identity_digest,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )


def _record_source_progress(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
    reconciled_transaction_id: UUID,
    observation_id: UUID,
    observation_updated_at: datetime,
    existing: RowMapping | None,
) -> None:
    if existing is None:
        connection.execute(
            reconciled_transaction_sources.insert().values(
                id=uuid4(),
                residence_id=residence_id,
                connection_id=connection_id,
                reconciled_transaction_id=reconciled_transaction_id,
                source_observation_id=observation_id,
                observation_updated_at=observation_updated_at,
                first_reconciled_at=func.transaction_timestamp(),
                updated_at=func.transaction_timestamp(),
            )
        )
        return

    if existing["reconciled_transaction_id"] != reconciled_transaction_id:
        raise TransactionReconciliationConflictError(
            "transaction reconciliation source target changed unexpectedly"
        )
    previous_updated_at = _aware_datetime(
        existing["observation_updated_at"],
        "source observation_updated_at",
    )
    if previous_updated_at > observation_updated_at:
        raise TransactionReconciliationConflictError(
            "transaction reconciliation source progress would regress"
        )
    if previous_updated_at == observation_updated_at:
        return

    source_id = _uuid_value(existing["id"], "reconciliation source id")
    updated_id = connection.scalar(
        update(reconciled_transaction_sources)
        .where(
            reconciled_transaction_sources.c.id == source_id,
            reconciled_transaction_sources.c.residence_id == residence_id,
            reconciled_transaction_sources.c.connection_id == connection_id,
            reconciled_transaction_sources.c.observation_updated_at
            == previous_updated_at,
        )
        .values(
            observation_updated_at=observation_updated_at,
            updated_at=func.transaction_timestamp(),
        )
        .returning(reconciled_transaction_sources.c.id)
    )
    if updated_id != source_id:
        raise TransactionReconciliationConflictError(
            "transaction reconciliation source progress changed concurrently"
        )


def _identity(
    *,
    residence_id: UUID,
    connection_id: UUID,
    external_account_record_id: UUID,
    external_resource_id: object,
    stable_fingerprint: object,
) -> tuple[ReconciledTransactionIdentityKind, str]:
    if external_resource_id is None:
        if (
            not isinstance(stable_fingerprint, str)
            or len(stable_fingerprint) != 64
            or any(
                character not in "0123456789abcdef" for character in stable_fingerprint
            )
        ):
            raise TransactionReconciliationError(
                "transaction reconciliation found an invalid fingerprint identity"
            )
        kind = ReconciledTransactionIdentityKind.FINGERPRINT
        identity_material = stable_fingerprint
    else:
        if not isinstance(external_resource_id, str) or not external_resource_id:
            raise TransactionReconciliationError(
                "transaction reconciliation found an invalid provider identity"
            )
        kind = ReconciledTransactionIdentityKind.PROVIDER_ID
        identity_material = external_resource_id

    material = "\x1f".join(
        (
            _RECONCILIATION_IDENTITY_NAMESPACE,
            str(residence_id),
            str(connection_id),
            str(external_account_record_id),
            "transactions",
            kind.value,
            identity_material,
        )
    )
    return kind, hashlib.sha256(material.encode("utf-8")).hexdigest()


def _stored_status(value: object) -> StoredTransactionObservationStatus:
    if not isinstance(value, str):
        raise TransactionReconciliationError(
            "transaction reconciliation found an invalid observation status"
        )
    try:
        return StoredTransactionObservationStatus(value)
    except ValueError:
        raise TransactionReconciliationError(
            "transaction reconciliation found an invalid observation status"
        ) from None


def _aware_datetime(value: object, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise TransactionReconciliationError(
            f"transaction reconciliation found invalid {field_name}"
        )
    return value


def _uuid_value(value: object, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise TransactionReconciliationError(
            f"transaction reconciliation found invalid {field_name}"
        )
    return value


def _clean_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("limit must be an integer")
    if value < 1 or value > _MAX_RECONCILIATION_LIMIT:
        raise ValueError(f"limit must be between 1 and {_MAX_RECONCILIATION_LIMIT}")
    return value


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


def _sqlstate(error: DBAPIError) -> str | None:
    value = getattr(error.orig, "sqlstate", None)
    return value if isinstance(value, str) else None


__all__ = ["BankingTransactionReconciliationStoreMixin"]
