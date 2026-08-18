"""Append-only persistence for canonical Movement classification and allocation."""

from __future__ import annotations

import hashlib
from uuid import UUID

from meufinanceiro_finance import (
    FinancialAuditEventDraft,
    FinancialAuditEventType,
    FinancialCategoryStatus,
    FinancialMovementAllocationDraft,
    FinancialMovementAllocationRecord,
    FinancialMovementAllocationRevisionDraft,
    FinancialMovementAllocationSetDraft,
    FinancialMovementAllocationSetRecord,
    FinancialMovementRole,
    FinancialResultEffect,
    FinancialVisibilityScope,
    Money,
    is_category_audience_compatible_for_movement,
    new_financial_resource_id,
    validate_financial_idempotency_key,
    validate_financial_resource_id,
)
from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.financial_audit_store import _append_financial_audit_event
from meufinanceiro_persistence.financial_category_schema import financial_categories
from meufinanceiro_persistence.financial_movement_allocation_schema import (
    financial_movement_allocation_sets,
    financial_movement_allocations,
)
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementAccessError,
    _require_active_membership,
    _set_context,
)

_REQUEST_DIGEST_NAMESPACE = "meufinanceiro:movement-allocation-operation:v1"


class FinancialMovementAllocationPersistenceError(RuntimeError):
    """Sanitized persistence failure for Movement classification operations."""


class FinancialMovementAllocationAccessError(
    FinancialMovementAllocationPersistenceError
):
    """Actor has no active membership in the requested residence."""


class FinancialMovementAllocationMovementNotFoundError(
    FinancialMovementAllocationPersistenceError
):
    """Target Movement is missing, invisible, or not eligible for mutation."""


class FinancialMovementAllocationCategoryNotFoundError(
    FinancialMovementAllocationPersistenceError
):
    """At least one requested category is missing, inactive, or incompatible."""


class FinancialMovementAllocationConflictError(
    FinancialMovementAllocationPersistenceError
):
    """Allocation revision or idempotency state conflicts with the request."""


class FinancialMovementAllocationNotFoundError(
    FinancialMovementAllocationPersistenceError
):
    """No visible allocation set exists for the requested Movement."""


class FinancialMovementAllocationStore:
    """Persist/read immutable allocation-set revisions for canonical Movements."""

    def __init__(self, engine: Engine) -> None:
        if not isinstance(engine, Engine):
            raise TypeError("engine must be SQLAlchemy Engine")
        self._engine = engine

    def create_allocation_set(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialMovementAllocationSetDraft,
    ) -> FinancialMovementAllocationSetRecord:
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        validate_financial_idempotency_key(idempotency_key)
        if not isinstance(draft, FinancialMovementAllocationSetDraft):
            raise TypeError("draft must be FinancialMovementAllocationSetDraft")

        allocations = draft.canonical_allocations()
        return self._mutate(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=idempotency_key,
            movement_id=draft.movement_id,
            supersedes_id=None,
            allocations=allocations,
            request_digest=_request_digest(
                operator_id=operator_id,
                movement_id=draft.movement_id,
                supersedes_id=None,
                allocations=allocations,
            ),
        )

    def revise_allocation_set(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialMovementAllocationRevisionDraft,
    ) -> FinancialMovementAllocationSetRecord:
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        validate_financial_idempotency_key(idempotency_key)
        if not isinstance(draft, FinancialMovementAllocationRevisionDraft):
            raise TypeError("draft must be FinancialMovementAllocationRevisionDraft")

        allocations = draft.canonical_allocations()
        return self._mutate(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=idempotency_key,
            movement_id=draft.movement_id,
            supersedes_id=draft.supersedes_id,
            allocations=allocations,
            request_digest=_request_digest(
                operator_id=operator_id,
                movement_id=draft.movement_id,
                supersedes_id=draft.supersedes_id,
                allocations=allocations,
            ),
        )

    def get_current_allocation_set(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        movement_id: UUID,
    ) -> FinancialMovementAllocationSetRecord:
        _validate_read_scope(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            movement_id=movement_id,
        )
        try:
            with self._engine.begin() as connection:
                _prepare_connection(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )
                row = _current_set_row(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    movement_id=movement_id,
                )
                if row is None:
                    raise FinancialMovementAllocationNotFoundError(
                        "financial Movement allocation was not found"
                    )
                return _set_record(connection, row)
        except FinancialMovementAccessError:
            raise FinancialMovementAllocationAccessError(
                "financial Movement allocation access denied"
            ) from None
        except (
            FinancialMovementAllocationAccessError,
            FinancialMovementAllocationNotFoundError,
        ):
            raise
        except DBAPIError:
            raise FinancialMovementAllocationPersistenceError(
                "financial Movement allocation could not be read"
            ) from None

    def list_allocation_history(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        movement_id: UUID,
    ) -> tuple[FinancialMovementAllocationSetRecord, ...]:
        _validate_read_scope(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            movement_id=movement_id,
        )
        try:
            with self._engine.begin() as connection:
                _prepare_connection(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )
                rows = (
                    connection.execute(
                        select(financial_movement_allocation_sets)
                        .where(
                            financial_movement_allocation_sets.c.installation_id
                            == installation_id,
                            financial_movement_allocation_sets.c.residence_id
                            == residence_id,
                            financial_movement_allocation_sets.c.movement_id
                            == movement_id,
                        )
                        .order_by(financial_movement_allocation_sets.c.revision)
                    )
                    .mappings()
                    .all()
                )
                return tuple(_set_record(connection, row) for row in rows)
        except FinancialMovementAccessError:
            raise FinancialMovementAllocationAccessError(
                "financial Movement allocation access denied"
            ) from None
        except DBAPIError:
            raise FinancialMovementAllocationPersistenceError(
                "financial Movement allocation history could not be read"
            ) from None

    def _mutate(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        movement_id: UUID,
        supersedes_id: UUID | None,
        allocations: tuple[FinancialMovementAllocationDraft, ...],
        request_digest: str,
    ) -> FinancialMovementAllocationSetRecord:
        try:
            with self._engine.begin() as connection:
                _prepare_connection(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )
                existing = _set_by_idempotency(
                    connection,
                    installation_id=installation_id,
                    idempotency_key=idempotency_key,
                )
                if existing is not None:
                    return _require_replay(connection, existing, request_digest)

                movement = _lock_eligible_movement(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    movement_id=movement_id,
                )
                if movement is None:
                    raise FinancialMovementAllocationMovementNotFoundError(
                        "financial Movement was not found"
                    )
                replay_after_lock = _set_by_idempotency(
                    connection,
                    installation_id=installation_id,
                    idempotency_key=idempotency_key,
                )
                if replay_after_lock is not None:
                    return _require_replay(
                        connection,
                        replay_after_lock,
                        request_digest,
                    )

                account = _owned_active_account(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    account_id=movement["account_id"],
                )
                if account is None:
                    raise FinancialMovementAllocationMovementNotFoundError(
                        "financial Movement was not found"
                    )
                _validate_economic_shape(movement=movement, allocations=allocations)
                _validate_categories(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    account=account,
                    allocations=allocations,
                )

                current = _current_set_row(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    movement_id=movement_id,
                )
                if supersedes_id is None:
                    if current is not None:
                        raise FinancialMovementAllocationConflictError(
                            "financial Movement is already classified"
                        )
                    revision = 1
                else:
                    if current is None or current["id"] != supersedes_id:
                        raise FinancialMovementAllocationConflictError(
                            "financial Movement allocation revision is stale"
                        )
                    revision = int(current["revision"]) + 1

                set_id = new_financial_resource_id()
                inserted = (
                    connection.execute(
                        pg_insert(financial_movement_allocation_sets)
                        .values(
                            id=set_id,
                            installation_id=installation_id,
                            residence_id=residence_id,
                            movement_id=movement_id,
                            revision=revision,
                            supersedes_id=supersedes_id,
                            created_by_operator_id=operator_id,
                            idempotency_key=idempotency_key,
                            request_digest=request_digest,
                            created_at=func.transaction_timestamp(),
                        )
                        .on_conflict_do_nothing(
                            index_elements=[
                                financial_movement_allocation_sets.c.installation_id,
                                financial_movement_allocation_sets.c.idempotency_key,
                            ]
                        )
                        .returning(*financial_movement_allocation_sets.c)
                    )
                    .mappings()
                    .one_or_none()
                )
                if inserted is None:
                    raced = _set_by_idempotency(
                        connection,
                        installation_id=installation_id,
                        idempotency_key=idempotency_key,
                    )
                    if raced is not None:
                        return _require_replay(connection, raced, request_digest)
                    raise FinancialMovementAllocationConflictError(
                        "financial Movement allocation conflict"
                    )

                for item in allocations:
                    connection.execute(
                        pg_insert(financial_movement_allocations).values(
                            id=new_financial_resource_id(),
                            allocation_set_id=set_id,
                            installation_id=installation_id,
                            residence_id=residence_id,
                            movement_id=movement_id,
                            category_id=item.category_id,
                            currency=item.amount.currency,
                            amount=item.amount.amount,
                            created_at=func.transaction_timestamp(),
                        )
                    )
                _append_financial_audit_event(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    actor_operator_id=operator_id,
                    draft=FinancialAuditEventDraft(
                        event_type=(
                            FinancialAuditEventType.ALLOCATION_SET_CREATED
                            if supersedes_id is None
                            else FinancialAuditEventType.ALLOCATION_SET_REVISED
                        ),
                        subject_id=set_id,
                        related_subject_id=supersedes_id,
                    ),
                )
                return _set_record(connection, inserted)
        except FinancialMovementAccessError:
            raise FinancialMovementAllocationAccessError(
                "financial Movement allocation access denied"
            ) from None
        except (
            FinancialMovementAllocationAccessError,
            FinancialMovementAllocationCategoryNotFoundError,
            FinancialMovementAllocationConflictError,
            FinancialMovementAllocationMovementNotFoundError,
            FinancialMovementAllocationPersistenceError,
        ):
            raise
        except IntegrityError:
            raise FinancialMovementAllocationConflictError(
                "financial Movement allocation conflict"
            ) from None
        except DBAPIError:
            raise FinancialMovementAllocationPersistenceError(
                "financial Movement allocation could not be persisted"
            ) from None


def _prepare_connection(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
) -> None:
    _set_context(
        connection,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
    )
    _require_active_membership(
        connection,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
    )


def _validate_read_scope(
    *, installation_id: UUID, residence_id: UUID, operator_id: UUID, movement_id: UUID
) -> None:
    _require_uuid(installation_id, "installation_id")
    _require_uuid(residence_id, "residence_id")
    _require_uuid(operator_id, "operator_id")
    validate_financial_resource_id(movement_id)


def _lock_eligible_movement(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    movement_id: UUID,
) -> RowMapping | None:
    return (
        connection.execute(
            select(financial_movements)
            .where(
                financial_movements.c.id == movement_id,
                financial_movements.c.installation_id == installation_id,
                financial_movements.c.residence_id == residence_id,
                financial_movements.c.role == FinancialMovementRole.STANDARD.value,
                financial_movements.c.result_effect.in_(
                    (
                        FinancialResultEffect.INCOME.value,
                        FinancialResultEffect.EXPENSE.value,
                    )
                ),
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )


def _owned_active_account(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
    account_id: UUID,
) -> RowMapping | None:
    return (
        connection.execute(
            select(financial_accounts).where(
                financial_accounts.c.id == account_id,
                financial_accounts.c.installation_id == installation_id,
                financial_accounts.c.residence_id == residence_id,
                financial_accounts.c.owner_operator_id == operator_id,
                financial_accounts.c.status == "ACTIVE",
            )
        )
        .mappings()
        .one_or_none()
    )


def _validate_economic_shape(
    *, movement: RowMapping, allocations: tuple[FinancialMovementAllocationDraft, ...]
) -> None:
    movement_money = Money(movement["amount"], movement["currency"])
    total = allocations[0].amount
    for item in allocations[1:]:
        total = total + item.amount
    if total != movement_money:
        raise FinancialMovementAllocationConflictError(
            "financial Movement allocation total does not match Movement"
        )
    if any(item.amount.currency != movement_money.currency for item in allocations):
        raise FinancialMovementAllocationConflictError(
            "financial Movement allocation currency does not match Movement"
        )
    movement_positive = movement_money.amount > 0
    if any((item.amount.amount > 0) != movement_positive for item in allocations):
        raise FinancialMovementAllocationConflictError(
            "financial Movement allocation sign does not match Movement"
        )


def _validate_categories(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    account: RowMapping,
    allocations: tuple[FinancialMovementAllocationDraft, ...],
) -> None:
    category_ids = tuple(item.category_id for item in allocations)
    rows = (
        connection.execute(
            select(financial_categories).where(
                financial_categories.c.id.in_(category_ids),
                financial_categories.c.installation_id == installation_id,
                financial_categories.c.residence_id == residence_id,
                financial_categories.c.status == FinancialCategoryStatus.ACTIVE.value,
            )
        )
        .mappings()
        .all()
    )
    by_id = {row["id"]: row for row in rows}
    if len(by_id) != len(category_ids):
        raise FinancialMovementAllocationCategoryNotFoundError(
            "financial category was not found"
        )
    movement_scope = FinancialVisibilityScope(account["visibility_scope"])
    movement_owner = account["owner_operator_id"]
    for category_id in category_ids:
        category = by_id[category_id]
        if not is_category_audience_compatible_for_movement(
            movement_visibility_scope=movement_scope,
            movement_owner_operator_id=movement_owner,
            category_visibility_scope=FinancialVisibilityScope(
                category["visibility_scope"]
            ),
            category_owner_operator_id=category["owner_operator_id"],
        ):
            raise FinancialMovementAllocationCategoryNotFoundError(
                "financial category was not found"
            )


def _current_set_row(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    movement_id: UUID,
) -> RowMapping | None:
    successor = financial_movement_allocation_sets.alias("successor")
    return (
        connection.execute(
            select(financial_movement_allocation_sets).where(
                financial_movement_allocation_sets.c.installation_id == installation_id,
                financial_movement_allocation_sets.c.residence_id == residence_id,
                financial_movement_allocation_sets.c.movement_id == movement_id,
                ~select(successor.c.id)
                .where(
                    successor.c.supersedes_id == financial_movement_allocation_sets.c.id
                )
                .exists(),
            )
        )
        .mappings()
        .one_or_none()
    )


def _set_by_idempotency(
    connection: Connection, *, installation_id: UUID, idempotency_key: UUID
) -> RowMapping | None:
    return (
        connection.execute(
            select(financial_movement_allocation_sets).where(
                financial_movement_allocation_sets.c.installation_id == installation_id,
                financial_movement_allocation_sets.c.idempotency_key == idempotency_key,
            )
        )
        .mappings()
        .one_or_none()
    )


def _set_record(
    connection: Connection, row: RowMapping
) -> FinancialMovementAllocationSetRecord:
    allocation_rows = (
        connection.execute(
            select(financial_movement_allocations)
            .where(financial_movement_allocations.c.allocation_set_id == row["id"])
            .order_by(financial_movement_allocations.c.category_id)
        )
        .mappings()
        .all()
    )
    allocations = tuple(
        FinancialMovementAllocationRecord(
            id=item["id"],
            allocation_set_id=item["allocation_set_id"],
            category_id=item["category_id"],
            amount=Money(item["amount"], item["currency"]),
            created_at=item["created_at"],
        )
        for item in allocation_rows
    )
    return FinancialMovementAllocationSetRecord(
        id=row["id"],
        movement_id=row["movement_id"],
        revision=int(row["revision"]),
        supersedes_id=row["supersedes_id"],
        created_by_operator_id=row["created_by_operator_id"],
        created_at=row["created_at"],
        allocations=allocations,
    )


def _require_replay(
    connection: Connection, row: RowMapping, request_digest: str
) -> FinancialMovementAllocationSetRecord:
    if row["request_digest"] != request_digest:
        raise FinancialMovementAllocationConflictError(
            "financial Movement allocation idempotency conflict"
        )
    return _set_record(connection, row)


def _request_digest(
    *,
    operator_id: UUID,
    movement_id: UUID,
    supersedes_id: UUID | None,
    allocations: tuple[FinancialMovementAllocationDraft, ...],
) -> str:
    material = [
        _REQUEST_DIGEST_NAMESPACE,
        str(operator_id),
        str(movement_id),
        str(supersedes_id) if supersedes_id is not None else "ROOT",
    ]
    for item in allocations:
        category_id, currency, amount = item.canonical_material()
        material.extend((category_id, currency, amount))
    return hashlib.sha256("\x1f".join(material).encode("utf-8")).hexdigest()


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


__all__ = [
    "FinancialMovementAllocationAccessError",
    "FinancialMovementAllocationCategoryNotFoundError",
    "FinancialMovementAllocationConflictError",
    "FinancialMovementAllocationMovementNotFoundError",
    "FinancialMovementAllocationNotFoundError",
    "FinancialMovementAllocationPersistenceError",
    "FinancialMovementAllocationStore",
]
