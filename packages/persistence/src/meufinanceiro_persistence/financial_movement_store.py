"""Idempotent append-only persistence for canonical financial Movements."""

from __future__ import annotations

import hashlib
from datetime import date
from uuid import UUID

from meufinanceiro_finance.ids import (
    new_financial_resource_id,
    validate_financial_resource_id,
)
from meufinanceiro_finance.money import Money
from meufinanceiro_finance.movement_records import FinancialMovementRecord
from meufinanceiro_finance.movements import (
    FinancialMovementDraft,
    FinancialMovementReversalDraft,
    FinancialMovementRole,
    FinancialResultEffect,
)
from meufinanceiro_finance.operation_ids import validate_financial_idempotency_key
from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_opening_balance_schema import (
    financial_opening_balances,
)
from meufinanceiro_persistence.household_schema import household_memberships

_REQUEST_DIGEST_NAMESPACE = "meufinanceiro:financial-movement-operation:v1"


class FinancialMovementPersistenceError(RuntimeError):
    """Sanitized persistence failure for canonical Movement operations."""


class FinancialMovementAccessError(FinancialMovementPersistenceError):
    """Actor has no active membership in the requested residence."""


class FinancialMovementAccountNotFoundError(FinancialMovementPersistenceError):
    """Target account is missing, inactive, invisible, or not owned for mutation."""


class FinancialMovementNotFoundError(FinancialMovementPersistenceError):
    """Movement is missing or outside the actor's effective account audience."""


class FinancialMovementIdempotencyConflictError(FinancialMovementPersistenceError):
    """An idempotency key was reused for different canonical request material."""


class FinancialMovementAlreadyReversedError(FinancialMovementPersistenceError):
    """The original Movement already has its unique full reversal."""


class FinancialMovementBeforeOpeningBalanceError(FinancialMovementPersistenceError):
    """Movement would precede the immutable opening-balance anchor."""


class FinancialMovementStore:
    """Create/read immutable Movements and derive full reversals transactionally."""

    def __init__(self, engine: Engine) -> None:
        if not isinstance(engine, Engine):
            raise TypeError("engine must be SQLAlchemy Engine")
        self._engine = engine

    def create_movement(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialMovementDraft,
    ) -> FinancialMovementRecord:
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        validate_financial_idempotency_key(idempotency_key)
        if not isinstance(draft, FinancialMovementDraft):
            raise TypeError("draft must be FinancialMovementDraft")

        request_digest = _standard_request_digest(operator_id, draft)
        try:
            with self._engine.begin() as connection:
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
                existing = _movement_by_idempotency(
                    connection,
                    installation_id=installation_id,
                    idempotency_key=idempotency_key,
                )
                if existing is not None:
                    return _require_replay(existing, request_digest)

                account_currency = _owned_active_account_currency(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    account_id=draft.account_id,
                )
                if account_currency != draft.amount.currency:
                    raise FinancialMovementAccountNotFoundError(
                        "financial account was not found"
                    )
                _require_not_before_opening(
                    connection,
                    account_id=draft.account_id,
                    effective_date=draft.effective_date,
                )

                movement_id = new_financial_resource_id()
                inserted = (
                    connection.execute(
                        pg_insert(financial_movements)
                        .values(
                            id=movement_id,
                            installation_id=installation_id,
                            residence_id=residence_id,
                            account_id=draft.account_id,
                            currency=draft.amount.currency,
                            amount=draft.amount.amount,
                            result_effect=draft.result_effect.value,
                            role=FinancialMovementRole.STANDARD.value,
                            effective_date=draft.effective_date,
                            competence_date=draft.competence_date,
                            description=draft.description,
                            reversal_of_id=None,
                            reversal_target_role=None,
                            reversal_reason=None,
                            created_by_operator_id=operator_id,
                            idempotency_key=idempotency_key,
                            request_digest=request_digest,
                            created_at=func.transaction_timestamp(),
                        )
                        .on_conflict_do_nothing(
                            index_elements=[
                                financial_movements.c.installation_id,
                                financial_movements.c.idempotency_key,
                            ]
                        )
                        .returning(*financial_movements.c)
                    )
                    .mappings()
                    .one_or_none()
                )
                if inserted is not None:
                    return _record(inserted)

                raced = _movement_by_idempotency(
                    connection,
                    installation_id=installation_id,
                    idempotency_key=idempotency_key,
                )
                if raced is None:
                    raise FinancialMovementIdempotencyConflictError(
                        "movement idempotency conflict"
                    )
                return _require_replay(raced, request_digest)
        except (
            FinancialMovementAccessError,
            FinancialMovementAccountNotFoundError,
            FinancialMovementBeforeOpeningBalanceError,
            FinancialMovementIdempotencyConflictError,
            FinancialMovementPersistenceError,
        ):
            raise
        except IntegrityError as error:
            raise _integrity_error(error) from None
        except DBAPIError:
            raise FinancialMovementPersistenceError(
                "financial Movement could not be persisted"
            ) from None

    def reverse_movement(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialMovementReversalDraft,
    ) -> FinancialMovementRecord:
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        validate_financial_idempotency_key(idempotency_key)
        if not isinstance(draft, FinancialMovementReversalDraft):
            raise TypeError("draft must be FinancialMovementReversalDraft")

        request_digest = _reversal_request_digest(operator_id, draft)
        try:
            with self._engine.begin() as connection:
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

                existing = _movement_by_idempotency(
                    connection,
                    installation_id=installation_id,
                    idempotency_key=idempotency_key,
                )
                if existing is not None:
                    return _require_replay(existing, request_digest)

                original = (
                    connection.execute(
                        select(financial_movements).where(
                            financial_movements.c.id == draft.movement_id,
                            financial_movements.c.installation_id == installation_id,
                            financial_movements.c.residence_id == residence_id,
                            financial_movements.c.role
                            == FinancialMovementRole.STANDARD.value,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if original is None:
                    raise FinancialMovementNotFoundError(
                        "financial Movement was not found"
                    )

                account_id = original["account_id"]
                currency = original["currency"]
                account_currency = _owned_active_account_currency(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    account_id=account_id,
                )
                if account_currency != currency:
                    raise FinancialMovementAccountNotFoundError(
                        "financial account was not found"
                    )
                _require_not_before_opening(
                    connection,
                    account_id=account_id,
                    effective_date=draft.effective_date,
                )
                _lock_standard_movement_for_reversal(
                    connection,
                    movement_id=draft.movement_id,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )

                # A concurrent retry may have committed while this transaction waited
                # for the original Movement lock.
                replay_after_lock = _movement_by_idempotency(
                    connection,
                    installation_id=installation_id,
                    idempotency_key=idempotency_key,
                )
                if replay_after_lock is not None:
                    return _require_replay(replay_after_lock, request_digest)

                prior_reversal = connection.scalar(
                    select(financial_movements.c.id).where(
                        financial_movements.c.reversal_of_id == draft.movement_id,
                        financial_movements.c.installation_id == installation_id,
                        financial_movements.c.residence_id == residence_id,
                    )
                )
                if prior_reversal is not None:
                    raise FinancialMovementAlreadyReversedError(
                        "financial Movement is already reversed"
                    )

                original_amount = Money(original["amount"], currency)
                reversal_amount = -original_amount
                movement_id = new_financial_resource_id()
                inserted = (
                    connection.execute(
                        pg_insert(financial_movements)
                        .values(
                            id=movement_id,
                            installation_id=installation_id,
                            residence_id=residence_id,
                            account_id=account_id,
                            currency=currency,
                            amount=reversal_amount.amount,
                            result_effect=original["result_effect"],
                            role=FinancialMovementRole.REVERSAL.value,
                            effective_date=draft.effective_date,
                            competence_date=draft.competence_date,
                            description=None,
                            reversal_of_id=draft.movement_id,
                            reversal_target_role=FinancialMovementRole.STANDARD.value,
                            reversal_reason=draft.reason,
                            created_by_operator_id=operator_id,
                            idempotency_key=idempotency_key,
                            request_digest=request_digest,
                            created_at=func.transaction_timestamp(),
                        )
                        .returning(*financial_movements.c)
                    )
                    .mappings()
                    .one()
                )
                return _record(inserted)
        except (
            FinancialMovementAccessError,
            FinancialMovementAccountNotFoundError,
            FinancialMovementAlreadyReversedError,
            FinancialMovementBeforeOpeningBalanceError,
            FinancialMovementIdempotencyConflictError,
            FinancialMovementNotFoundError,
            FinancialMovementPersistenceError,
        ):
            raise
        except IntegrityError as error:
            raise _integrity_error(error) from None
        except DBAPIError:
            raise FinancialMovementPersistenceError(
                "financial Movement reversal could not be persisted"
            ) from None

    def get_movement(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        movement_id: UUID,
    ) -> FinancialMovementRecord:
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        validate_financial_resource_id(movement_id)

        try:
            with self._engine.begin() as connection:
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
                row = (
                    connection.execute(
                        select(financial_movements).where(
                            financial_movements.c.id == movement_id,
                            financial_movements.c.installation_id == installation_id,
                            financial_movements.c.residence_id == residence_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except (FinancialMovementAccessError, FinancialMovementPersistenceError):
            raise
        except DBAPIError:
            raise FinancialMovementPersistenceError(
                "financial Movement could not be read"
            ) from None

        if row is None:
            raise FinancialMovementNotFoundError("financial Movement was not found")
        return _record(row)

    def list_movements(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID,
    ) -> tuple[FinancialMovementRecord, ...]:
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        validate_financial_resource_id(account_id)

        try:
            with self._engine.begin() as connection:
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
                visible_account = connection.scalar(
                    select(financial_accounts.c.id).where(
                        financial_accounts.c.id == account_id,
                        financial_accounts.c.installation_id == installation_id,
                        financial_accounts.c.residence_id == residence_id,
                    )
                )
                if visible_account is None:
                    raise FinancialMovementAccountNotFoundError(
                        "financial account was not found"
                    )
                rows = (
                    connection.execute(
                        select(financial_movements)
                        .where(
                            financial_movements.c.account_id == account_id,
                            financial_movements.c.installation_id == installation_id,
                            financial_movements.c.residence_id == residence_id,
                        )
                        .order_by(
                            financial_movements.c.effective_date,
                            financial_movements.c.created_at,
                            financial_movements.c.id,
                        )
                    )
                    .mappings()
                    .all()
                )
        except (
            FinancialMovementAccessError,
            FinancialMovementAccountNotFoundError,
            FinancialMovementPersistenceError,
        ):
            raise
        except DBAPIError:
            raise FinancialMovementPersistenceError(
                "financial Movements could not be read"
            ) from None

        return tuple(_record(row) for row in rows)


def _set_context(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
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
            func.set_config(
                "app.current_operator_id",
                str(operator_id),
                True,
            ),
        )
    )


def _require_active_membership(
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
        raise FinancialMovementAccessError("financial Movement access denied")


def _owned_active_account_currency(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
    account_id: UUID,
) -> str:
    currency = connection.scalar(
        select(financial_accounts.c.currency).where(
            financial_accounts.c.id == account_id,
            financial_accounts.c.installation_id == installation_id,
            financial_accounts.c.residence_id == residence_id,
            financial_accounts.c.owner_operator_id == operator_id,
            financial_accounts.c.status == "ACTIVE",
        )
    )
    if not isinstance(currency, str):
        raise FinancialMovementAccountNotFoundError("financial account was not found")
    return currency


def _lock_standard_movement_for_reversal(
    connection: Connection,
    *,
    movement_id: UUID,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
) -> None:
    locked = connection.scalar(
        select(
            func.finance.lock_standard_movement_for_reversal(
                movement_id,
                installation_id,
                residence_id,
                operator_id,
            )
        )
    )
    if locked is not True:
        raise FinancialMovementAccountNotFoundError("financial account was not found")


def _require_not_before_opening(
    connection: Connection,
    *,
    account_id: UUID,
    effective_date: date,
) -> None:
    opening_date = connection.scalar(
        select(financial_opening_balances.c.effective_date).where(
            financial_opening_balances.c.account_id == account_id
        )
    )
    if opening_date is not None and effective_date < opening_date:
        raise FinancialMovementBeforeOpeningBalanceError(
            "financial Movement must not precede opening balance"
        )


def _movement_by_idempotency(
    connection: Connection,
    *,
    installation_id: UUID,
    idempotency_key: UUID,
) -> RowMapping | None:
    return (
        connection.execute(
            select(financial_movements).where(
                financial_movements.c.installation_id == installation_id,
                financial_movements.c.idempotency_key == idempotency_key,
            )
        )
        .mappings()
        .one_or_none()
    )


def _require_replay(row: RowMapping, request_digest: str) -> FinancialMovementRecord:
    if row["request_digest"] != request_digest:
        raise FinancialMovementIdempotencyConflictError(
            "movement idempotency key was reused for another request"
        )
    return _record(row)


def _standard_request_digest(
    operator_id: UUID,
    draft: FinancialMovementDraft,
) -> str:
    return _request_digest(
        "STANDARD",
        str(operator_id),
        str(draft.account_id),
        draft.amount.currency,
        draft.amount.canonical_amount,
        draft.result_effect.value,
        draft.effective_date.isoformat(),
        draft.competence_date.isoformat(),
        draft.description,
    )


def _reversal_request_digest(
    operator_id: UUID,
    draft: FinancialMovementReversalDraft,
) -> str:
    return _request_digest(
        "REVERSAL",
        str(operator_id),
        str(draft.movement_id),
        draft.effective_date.isoformat(),
        draft.competence_date.isoformat(),
        draft.reason,
    )


def _request_digest(*parts: str) -> str:
    material = "\x1f".join((_REQUEST_DIGEST_NAMESPACE, *parts))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _record(row: RowMapping) -> FinancialMovementRecord:
    try:
        return FinancialMovementRecord(
            id=row["id"],
            account_id=row["account_id"],
            amount=Money(row["amount"], row["currency"]),
            result_effect=FinancialResultEffect(row["result_effect"]),
            role=FinancialMovementRole(row["role"]),
            effective_date=row["effective_date"],
            competence_date=row["competence_date"],
            description=row["description"],
            reversal_of_id=row["reversal_of_id"],
            reversal_reason=row["reversal_reason"],
            created_by_operator_id=row["created_by_operator_id"],
            created_at=row["created_at"],
        )
    except (KeyError, TypeError, ValueError):
        raise FinancialMovementPersistenceError(
            "financial Movement state is invalid"
        ) from None


def _integrity_error(error: IntegrityError) -> FinancialMovementPersistenceError:
    name = _constraint_name(error)
    if name == "uq_finance_movements_idempotency":
        return FinancialMovementIdempotencyConflictError(
            "movement idempotency conflict"
        )
    if name == "uq_finance_movements_one_reversal":
        return FinancialMovementAlreadyReversedError(
            "financial Movement is already reversed"
        )
    return FinancialMovementPersistenceError(
        "financial Movement could not be persisted"
    )


def _constraint_name(error: IntegrityError) -> str | None:
    diagnostic = getattr(error.orig, "diag", None)
    value = getattr(diagnostic, "constraint_name", None)
    return value if isinstance(value, str) else None


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


__all__ = [
    "FinancialMovementAccessError",
    "FinancialMovementAccountNotFoundError",
    "FinancialMovementAlreadyReversedError",
    "FinancialMovementBeforeOpeningBalanceError",
    "FinancialMovementIdempotencyConflictError",
    "FinancialMovementNotFoundError",
    "FinancialMovementPersistenceError",
    "FinancialMovementStore",
]
