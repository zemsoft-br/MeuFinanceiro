"""Atomic append-only persistence for canonical internal financial transfers."""

from __future__ import annotations

import hashlib
from uuid import UUID

from meufinanceiro_finance.ids import (
    new_financial_resource_id,
    validate_financial_resource_id,
)
from meufinanceiro_finance.money import Money
from meufinanceiro_finance.movements import (
    FinancialMovementDraft,
    FinancialMovementReversalDraft,
    FinancialMovementRole,
)
from meufinanceiro_finance.operation_ids import (
    new_financial_idempotency_key,
    validate_financial_idempotency_key,
)
from meufinanceiro_finance.transfer_records import FinancialTransferRecord
from meufinanceiro_finance.transfers import (
    FinancialTransferDraft,
    FinancialTransferReversalDraft,
    FinancialTransferRole,
)
from sqlalchemy import Connection, Engine, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementAccessError,
    FinancialMovementAccountNotFoundError,
    FinancialMovementAlreadyReversedError,
    FinancialMovementBeforeOpeningBalanceError,
    FinancialMovementNotFoundError,
    _lock_standard_movement_for_reversal,
    _owned_active_account_currency,
    _require_active_membership,
    _require_not_before_opening,
    _reversal_request_digest,
    _set_context,
    _standard_request_digest,
)
from meufinanceiro_persistence.financial_transfer_schema import (
    financial_transfer_legs,
    financial_transfers,
)

_TRANSFER_REQUEST_DIGEST_NAMESPACE = "meufinanceiro:financial-transfer-operation:v1"
_SOURCE = "SOURCE"
_DESTINATION = "DESTINATION"


class FinancialTransferPersistenceError(RuntimeError):
    """Sanitized persistence failure for canonical transfer operations."""


class FinancialTransferAccessError(FinancialTransferPersistenceError):
    """Actor has no active membership in the requested residence."""


class FinancialTransferAccountNotFoundError(FinancialTransferPersistenceError):
    """One transfer endpoint is missing, inactive, invisible, or not owned."""


class FinancialTransferNotFoundError(FinancialTransferPersistenceError):
    """Transfer is missing or outside the actor's effective audience."""


class FinancialTransferIdempotencyConflictError(FinancialTransferPersistenceError):
    """An idempotency key was reused for different transfer request material."""


class FinancialTransferAlreadyReversedError(FinancialTransferPersistenceError):
    """The original transfer already has its unique full reversal."""


class FinancialTransferBeforeOpeningBalanceError(FinancialTransferPersistenceError):
    """At least one transfer leg would precede its opening-balance anchor."""


class FinancialTransferStore:
    """Create/read/reverse two-leg transfers in one PostgreSQL transaction."""

    def __init__(self, engine: Engine) -> None:
        if not isinstance(engine, Engine):
            raise TypeError("engine must be SQLAlchemy Engine")
        self._engine = engine

    def create_transfer(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialTransferDraft,
    ) -> FinancialTransferRecord:
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        validate_financial_idempotency_key(idempotency_key)
        if not isinstance(draft, FinancialTransferDraft):
            raise TypeError("draft must be FinancialTransferDraft")

        request_digest = _standard_transfer_request_digest(operator_id, draft)
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

                existing = _transfer_by_idempotency(
                    connection,
                    installation_id=installation_id,
                    idempotency_key=idempotency_key,
                )
                if existing is not None:
                    return _require_replay(existing, request_digest)

                _require_owned_same_currency_accounts(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    source_account_id=draft.source_account_id,
                    destination_account_id=draft.destination_account_id,
                    currency=draft.magnitude.currency,
                )

                transfer_id = new_financial_resource_id()
                source_movement_id = new_financial_resource_id()
                destination_movement_id = new_financial_resource_id()
                inserted = (
                    connection.execute(
                        pg_insert(financial_transfers)
                        .values(
                            id=transfer_id,
                            installation_id=installation_id,
                            residence_id=residence_id,
                            source_account_id=draft.source_account_id,
                            destination_account_id=draft.destination_account_id,
                            currency=draft.magnitude.currency,
                            role=FinancialTransferRole.STANDARD.value,
                            reversal_of_id=None,
                            created_by_operator_id=operator_id,
                            idempotency_key=idempotency_key,
                            request_digest=request_digest,
                            created_at=func.transaction_timestamp(),
                        )
                        .on_conflict_do_nothing(
                            index_elements=[
                                financial_transfers.c.installation_id,
                                financial_transfers.c.idempotency_key,
                            ]
                        )
                        .returning(*financial_transfers.c)
                    )
                    .mappings()
                    .one_or_none()
                )
                if inserted is None:
                    raced = _transfer_by_idempotency(
                        connection,
                        installation_id=installation_id,
                        idempotency_key=idempotency_key,
                    )
                    if raced is None:
                        raise FinancialTransferIdempotencyConflictError(
                            "transfer idempotency conflict"
                        )
                    return _require_replay(raced, request_digest)

                _insert_leg_links(
                    connection,
                    transfer_id=transfer_id,
                    source_movement_id=source_movement_id,
                    destination_movement_id=destination_movement_id,
                )
                source_draft, destination_draft = draft.to_movement_drafts()
                _insert_standard_leg(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    movement_id=source_movement_id,
                    idempotency_key=new_financial_idempotency_key(),
                    draft=source_draft,
                )
                _insert_standard_leg(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    movement_id=destination_movement_id,
                    idempotency_key=new_financial_idempotency_key(),
                    draft=destination_draft,
                )
                return _record(
                    inserted,
                    source_movement_id=source_movement_id,
                    destination_movement_id=destination_movement_id,
                )
        except FinancialMovementAccessError:
            raise FinancialTransferAccessError(
                "financial transfer access denied"
            ) from None
        except FinancialMovementAccountNotFoundError:
            raise FinancialTransferAccountNotFoundError(
                "financial transfer account was not found"
            ) from None
        except FinancialMovementBeforeOpeningBalanceError:
            raise FinancialTransferBeforeOpeningBalanceError(
                "financial transfer must not precede opening balance"
            ) from None
        except (
            FinancialTransferAccessError,
            FinancialTransferAccountNotFoundError,
            FinancialTransferBeforeOpeningBalanceError,
            FinancialTransferIdempotencyConflictError,
            FinancialTransferPersistenceError,
        ):
            raise
        except IntegrityError as error:
            raise _integrity_error(error) from None
        except DBAPIError:
            raise FinancialTransferPersistenceError(
                "financial transfer could not be persisted"
            ) from None

    def reverse_transfer(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialTransferReversalDraft,
    ) -> FinancialTransferRecord:
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        validate_financial_idempotency_key(idempotency_key)
        if not isinstance(draft, FinancialTransferReversalDraft):
            raise TypeError("draft must be FinancialTransferReversalDraft")

        request_digest = _reversal_transfer_request_digest(operator_id, draft)
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

                existing = _transfer_by_idempotency(
                    connection,
                    installation_id=installation_id,
                    idempotency_key=idempotency_key,
                )
                if existing is not None:
                    return _require_replay(existing, request_digest)

                original = _standard_transfer(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    transfer_id=draft.transfer_id,
                )
                if original is None:
                    raise FinancialTransferNotFoundError(
                        "financial transfer was not found"
                    )

                _require_owned_same_currency_accounts(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    source_account_id=original["source_account_id"],
                    destination_account_id=original["destination_account_id"],
                    currency=original["currency"],
                )

                prior_reversal = connection.scalar(
                    select(financial_transfers.c.id).where(
                        financial_transfers.c.reversal_of_id == draft.transfer_id,
                        financial_transfers.c.installation_id == installation_id,
                        financial_transfers.c.residence_id == residence_id,
                    )
                )
                if prior_reversal is not None:
                    raise FinancialTransferAlreadyReversedError(
                        "financial transfer is already reversed"
                    )

                reversal_transfer_id = new_financial_resource_id()
                source_movement_id = new_financial_resource_id()
                destination_movement_id = new_financial_resource_id()
                inserted = (
                    connection.execute(
                        pg_insert(financial_transfers)
                        .values(
                            id=reversal_transfer_id,
                            installation_id=installation_id,
                            residence_id=residence_id,
                            source_account_id=original["destination_account_id"],
                            destination_account_id=original["source_account_id"],
                            currency=original["currency"],
                            role=FinancialTransferRole.REVERSAL.value,
                            reversal_of_id=draft.transfer_id,
                            created_by_operator_id=operator_id,
                            idempotency_key=idempotency_key,
                            request_digest=request_digest,
                            created_at=func.transaction_timestamp(),
                        )
                        .on_conflict_do_nothing()
                        .returning(*financial_transfers.c)
                    )
                    .mappings()
                    .one_or_none()
                )
                if inserted is None:
                    raced = _transfer_by_idempotency(
                        connection,
                        installation_id=installation_id,
                        idempotency_key=idempotency_key,
                    )
                    if raced is not None:
                        return _require_replay(raced, request_digest)
                    raise FinancialTransferAlreadyReversedError(
                        "financial transfer is already reversed"
                    )

                _insert_leg_links(
                    connection,
                    transfer_id=reversal_transfer_id,
                    source_movement_id=source_movement_id,
                    destination_movement_id=destination_movement_id,
                )
                _insert_reversal_leg(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    movement_id=source_movement_id,
                    idempotency_key=new_financial_idempotency_key(),
                    draft=FinancialMovementReversalDraft(
                        movement_id=original["destination_movement_id"],
                        effective_date=draft.effective_date,
                        competence_date=draft.competence_date,
                        reason=draft.reason,
                    ),
                )
                _insert_reversal_leg(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    movement_id=destination_movement_id,
                    idempotency_key=new_financial_idempotency_key(),
                    draft=FinancialMovementReversalDraft(
                        movement_id=original["source_movement_id"],
                        effective_date=draft.effective_date,
                        competence_date=draft.competence_date,
                        reason=draft.reason,
                    ),
                )
                return _record(
                    inserted,
                    source_movement_id=source_movement_id,
                    destination_movement_id=destination_movement_id,
                )
        except FinancialMovementAccessError:
            raise FinancialTransferAccessError(
                "financial transfer access denied"
            ) from None
        except FinancialMovementAccountNotFoundError:
            raise FinancialTransferAccountNotFoundError(
                "financial transfer account was not found"
            ) from None
        except FinancialMovementBeforeOpeningBalanceError:
            raise FinancialTransferBeforeOpeningBalanceError(
                "financial transfer must not precede opening balance"
            ) from None
        except FinancialMovementAlreadyReversedError:
            raise FinancialTransferAlreadyReversedError(
                "financial transfer is already reversed"
            ) from None
        except FinancialMovementNotFoundError:
            raise FinancialTransferNotFoundError(
                "financial transfer Movement was not found"
            ) from None
        except (
            FinancialTransferAccessError,
            FinancialTransferAccountNotFoundError,
            FinancialTransferAlreadyReversedError,
            FinancialTransferBeforeOpeningBalanceError,
            FinancialTransferIdempotencyConflictError,
            FinancialTransferNotFoundError,
            FinancialTransferPersistenceError,
        ):
            raise
        except IntegrityError as error:
            raise _integrity_error(error) from None
        except DBAPIError:
            raise FinancialTransferPersistenceError(
                "financial transfer reversal could not be persisted"
            ) from None

    def get_transfer(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        transfer_id: UUID,
    ) -> FinancialTransferRecord:
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        validate_financial_resource_id(transfer_id)

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
                row = _transfer_by_id(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    transfer_id=transfer_id,
                )
        except FinancialMovementAccessError:
            raise FinancialTransferAccessError(
                "financial transfer access denied"
            ) from None
        except DBAPIError:
            raise FinancialTransferPersistenceError(
                "financial transfer could not be read"
            ) from None

        if row is None:
            raise FinancialTransferNotFoundError("financial transfer was not found")
        return _record(row)

    def list_transfers(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        account_id: UUID | None = None,
    ) -> tuple[FinancialTransferRecord, ...]:
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        if account_id is not None:
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
                statement = _transfer_select().where(
                    financial_transfers.c.installation_id == installation_id,
                    financial_transfers.c.residence_id == residence_id,
                )
                if account_id is not None:
                    statement = statement.where(
                        or_(
                            financial_transfers.c.source_account_id == account_id,
                            financial_transfers.c.destination_account_id == account_id,
                        )
                    )
                rows = (
                    connection.execute(
                        statement.order_by(
                            financial_transfers.c.created_at,
                            financial_transfers.c.id,
                        )
                    )
                    .mappings()
                    .all()
                )
        except FinancialMovementAccessError:
            raise FinancialTransferAccessError(
                "financial transfer access denied"
            ) from None
        except DBAPIError:
            raise FinancialTransferPersistenceError(
                "financial transfers could not be read"
            ) from None

        return tuple(_record(row) for row in rows)


def _transfer_select():  # type: ignore[no-untyped-def]
    source_leg = financial_transfer_legs.alias("source_leg")
    destination_leg = financial_transfer_legs.alias("destination_leg")
    return (
        select(
            financial_transfers,
            source_leg.c.movement_id.label("source_movement_id"),
            destination_leg.c.movement_id.label("destination_movement_id"),
        )
        .join(
            source_leg,
            (source_leg.c.transfer_id == financial_transfers.c.id)
            & (source_leg.c.direction == _SOURCE),
        )
        .join(
            destination_leg,
            (destination_leg.c.transfer_id == financial_transfers.c.id)
            & (destination_leg.c.direction == _DESTINATION),
        )
    )


def _require_owned_same_currency_accounts(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
    source_account_id: UUID,
    destination_account_id: UUID,
    currency: str,
) -> None:
    source_currency = _owned_active_account_currency(
        connection,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
        account_id=source_account_id,
    )
    destination_currency = _owned_active_account_currency(
        connection,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
        account_id=destination_account_id,
    )
    if source_currency != currency or destination_currency != currency:
        raise FinancialTransferAccountNotFoundError(
            "financial transfer account was not found"
        )


def _insert_leg_links(
    connection: Connection,
    *,
    transfer_id: UUID,
    source_movement_id: UUID,
    destination_movement_id: UUID,
) -> None:
    connection.execute(
        pg_insert(financial_transfer_legs),
        (
            {
                "transfer_id": transfer_id,
                "direction": _SOURCE,
                "movement_id": source_movement_id,
            },
            {
                "transfer_id": transfer_id,
                "direction": _DESTINATION,
                "movement_id": destination_movement_id,
            },
        ),
    )


def _insert_standard_leg(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
    movement_id: UUID,
    idempotency_key: UUID,
    draft: FinancialMovementDraft,
) -> None:
    validate_financial_resource_id(movement_id)
    validate_financial_idempotency_key(idempotency_key)
    account_currency = _owned_active_account_currency(
        connection,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
        account_id=draft.account_id,
    )
    if account_currency != draft.amount.currency:
        raise FinancialMovementAccountNotFoundError("financial account was not found")
    _require_not_before_opening(
        connection,
        account_id=draft.account_id,
        effective_date=draft.effective_date,
    )
    connection.execute(
        pg_insert(financial_movements).values(
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
            request_digest=_standard_request_digest(operator_id, draft),
            created_at=func.transaction_timestamp(),
        )
    )


def _insert_reversal_leg(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
    movement_id: UUID,
    idempotency_key: UUID,
    draft: FinancialMovementReversalDraft,
) -> None:
    validate_financial_resource_id(movement_id)
    validate_financial_idempotency_key(idempotency_key)
    original = (
        connection.execute(
            select(financial_movements).where(
                financial_movements.c.id == draft.movement_id,
                financial_movements.c.installation_id == installation_id,
                financial_movements.c.residence_id == residence_id,
                financial_movements.c.role == FinancialMovementRole.STANDARD.value,
            )
        )
        .mappings()
        .one_or_none()
    )
    if original is None:
        raise FinancialMovementNotFoundError("financial Movement was not found")

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
        raise FinancialMovementAccountNotFoundError("financial account was not found")
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
    connection.execute(
        pg_insert(financial_movements).values(
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
            request_digest=_reversal_request_digest(operator_id, draft),
            created_at=func.transaction_timestamp(),
        )
    )


def _transfer_by_idempotency(
    connection: Connection,
    *,
    installation_id: UUID,
    idempotency_key: UUID,
) -> RowMapping | None:
    return (
        connection.execute(
            _transfer_select().where(
                financial_transfers.c.installation_id == installation_id,
                financial_transfers.c.idempotency_key == idempotency_key,
            )
        )
        .mappings()
        .one_or_none()
    )


def _transfer_by_id(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    transfer_id: UUID,
) -> RowMapping | None:
    return (
        connection.execute(
            _transfer_select().where(
                financial_transfers.c.id == transfer_id,
                financial_transfers.c.installation_id == installation_id,
                financial_transfers.c.residence_id == residence_id,
            )
        )
        .mappings()
        .one_or_none()
    )


def _standard_transfer(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    transfer_id: UUID,
) -> RowMapping | None:
    return (
        connection.execute(
            _transfer_select().where(
                financial_transfers.c.id == transfer_id,
                financial_transfers.c.installation_id == installation_id,
                financial_transfers.c.residence_id == residence_id,
                financial_transfers.c.role == FinancialTransferRole.STANDARD.value,
            )
        )
        .mappings()
        .one_or_none()
    )


def _require_replay(row: RowMapping, request_digest: str) -> FinancialTransferRecord:
    if row["request_digest"] != request_digest:
        raise FinancialTransferIdempotencyConflictError(
            "transfer idempotency key was reused for another request"
        )
    return _record(row)


def _standard_transfer_request_digest(
    operator_id: UUID,
    draft: FinancialTransferDraft,
) -> str:
    return _request_digest(
        "STANDARD",
        str(operator_id),
        str(draft.source_account_id),
        str(draft.destination_account_id),
        draft.magnitude.currency,
        draft.magnitude.canonical_amount,
        draft.effective_date.isoformat(),
        draft.competence_date.isoformat(),
        draft.description,
    )


def _reversal_transfer_request_digest(
    operator_id: UUID,
    draft: FinancialTransferReversalDraft,
) -> str:
    return _request_digest(
        "REVERSAL",
        str(operator_id),
        str(draft.transfer_id),
        draft.effective_date.isoformat(),
        draft.competence_date.isoformat(),
        draft.reason,
    )


def _request_digest(*parts: str) -> str:
    material = "\x1f".join((_TRANSFER_REQUEST_DIGEST_NAMESPACE, *parts))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _record(
    row: RowMapping,
    *,
    source_movement_id: UUID | None = None,
    destination_movement_id: UUID | None = None,
) -> FinancialTransferRecord:
    try:
        source_id = source_movement_id or row["source_movement_id"]
        destination_id = destination_movement_id or row["destination_movement_id"]
        return FinancialTransferRecord(
            id=row["id"],
            source_account_id=row["source_account_id"],
            destination_account_id=row["destination_account_id"],
            currency=row["currency"],
            source_movement_id=source_id,
            destination_movement_id=destination_id,
            role=FinancialTransferRole(row["role"]),
            reversal_of_id=row["reversal_of_id"],
            created_by_operator_id=row["created_by_operator_id"],
            created_at=row["created_at"],
        )
    except (KeyError, TypeError, ValueError):
        raise FinancialTransferPersistenceError(
            "financial transfer state is invalid"
        ) from None


def _integrity_error(error: IntegrityError) -> FinancialTransferPersistenceError:
    name = _constraint_name(error)
    if name == "uq_finance_transfers_idempotency":
        return FinancialTransferIdempotencyConflictError(
            "transfer idempotency conflict"
        )
    if name in {
        "uq_finance_transfers_one_reversal",
        "uq_finance_movements_one_reversal",
    }:
        return FinancialTransferAlreadyReversedError(
            "financial transfer is already reversed"
        )
    return FinancialTransferPersistenceError(
        "financial transfer could not be persisted"
    )


def _constraint_name(error: IntegrityError) -> str | None:
    diagnostic = getattr(error.orig, "diag", None)
    value = getattr(diagnostic, "constraint_name", None)
    return value if isinstance(value, str) else None


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


__all__ = [
    "FinancialTransferAccessError",
    "FinancialTransferAccountNotFoundError",
    "FinancialTransferAlreadyReversedError",
    "FinancialTransferBeforeOpeningBalanceError",
    "FinancialTransferIdempotencyConflictError",
    "FinancialTransferNotFoundError",
    "FinancialTransferPersistenceError",
    "FinancialTransferStore",
]
