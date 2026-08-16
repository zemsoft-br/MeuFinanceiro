"""Atomic provider-neutral bridge from reconciled banking state to the ledger."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from uuid import UUID, uuid4

from meufinanceiro_finance.ids import new_financial_resource_id
from meufinanceiro_finance.money import Money
from meufinanceiro_finance.movements import (
    FinancialMovementDraft,
    FinancialMovementRole,
    FinancialResultEffect,
)
from meufinanceiro_finance.operation_ids import validate_financial_idempotency_key
from sqlalchemy import Connection, Engine, and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.banking_ledger_review_models import (
    BankingLedgerReviewAccessError,
    BankingLedgerReviewCandidate,
    BankingLedgerReviewConflictError,
    BankingLedgerReviewDecision,
    BankingLedgerReviewDraft,
    BankingLedgerReviewNotEligibleError,
    BankingLedgerReviewNotFoundError,
    BankingLedgerReviewPersistenceError,
    BankingLedgerReviewRecord,
)
from meufinanceiro_persistence.banking_ledger_review_schema import (
    reconciled_transaction_ledger_links,
)
from meufinanceiro_persistence.banking_observation_models import (
    StoredTransactionObservationStatus,
)
from meufinanceiro_persistence.banking_observation_schema import external_observations
from meufinanceiro_persistence.banking_reconciliation_schema import (
    reconciled_transactions,
)
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementAccessError,
    FinancialMovementAccountNotFoundError,
    FinancialMovementBeforeOpeningBalanceError,
    FinancialMovementIdempotencyConflictError,
    FinancialMovementPersistenceError,
    _integrity_error,
    _movement_by_idempotency,
    _owned_active_account_currency,
    _record as _movement_record,
    _require_active_membership,
    _require_not_before_opening,
    _require_replay as _require_movement_replay,
    _standard_request_digest,
)
from meufinanceiro_persistence.schema import connections

_REVIEW_DIGEST_NAMESPACE = "meufinanceiro:banking-ledger-review:v1"
_MOVEMENT_KEY_NAMESPACE = "meufinanceiro:banking-ledger-review:movement:v1"
_DEFAULT_DESCRIPTION = "Lançamento bancário importado"


class BankingLedgerReviewStore:
    """Review reconciled banking state without auto-promoting it to the ledger."""

    def __init__(self, engine: Engine) -> None:
        if not isinstance(engine, Engine):
            raise TypeError("engine must be SQLAlchemy Engine")
        self._engine = engine

    def get_candidate(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        reconciled_transaction_id: UUID,
    ) -> BankingLedgerReviewCandidate:
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        _require_uuid(reconciled_transaction_id, "reconciled_transaction_id")

        try:
            with self._engine.begin() as connection:
                _set_context(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )
                _require_review_membership(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )
                reconciled, observation = _load_review_source(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    reconciled_transaction_id=reconciled_transaction_id,
                    lock=False,
                )
                return _candidate(reconciled, observation)
        except (
            BankingLedgerReviewAccessError,
            BankingLedgerReviewNotFoundError,
            BankingLedgerReviewPersistenceError,
        ):
            raise
        except DBAPIError:
            raise BankingLedgerReviewPersistenceError(
                "banking ledger review candidate could not be read"
            ) from None

    def decide(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        reconciled_transaction_id: UUID,
        idempotency_key: UUID,
        draft: BankingLedgerReviewDraft,
    ) -> BankingLedgerReviewRecord:
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        _require_uuid(reconciled_transaction_id, "reconciled_transaction_id")
        validate_financial_idempotency_key(idempotency_key)
        if not isinstance(draft, BankingLedgerReviewDraft):
            raise TypeError("draft must be BankingLedgerReviewDraft")

        request_digest = _review_request_digest(
            operator_id=operator_id,
            reconciled_transaction_id=reconciled_transaction_id,
            draft=draft,
        )

        try:
            with self._engine.begin() as connection:
                _set_context(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )
                _require_review_membership(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )

                replay = _link_by_idempotency(
                    connection,
                    installation_id=installation_id,
                    idempotency_key=idempotency_key,
                )
                if replay is not None:
                    return _require_review_replay(replay, request_digest)

                reconciled, observation = _load_review_source(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    reconciled_transaction_id=reconciled_transaction_id,
                    lock=True,
                )
                _require_source_snapshot(reconciled, observation, draft)

                existing = _link_by_reconciled(
                    connection,
                    residence_id=residence_id,
                    connection_id=reconciled["connection_id"],
                    reconciled_transaction_id=reconciled_transaction_id,
                )
                if existing is not None:
                    raise BankingLedgerReviewConflictError(
                        "reconciled transaction already has a ledger decision"
                    )

                (
                    financial_account_id,
                    movement_id,
                    movement_effect,
                    movement_role,
                ) = _apply_decision(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    idempotency_key=idempotency_key,
                    draft=draft,
                    reconciled=reconciled,
                    observation=observation,
                )

                inserted = (
                    connection.execute(
                        pg_insert(reconciled_transaction_ledger_links)
                        .values(
                            id=uuid4(),
                            installation_id=installation_id,
                            residence_id=residence_id,
                            connection_id=reconciled["connection_id"],
                            reconciled_transaction_id=reconciled_transaction_id,
                            source_observation_id=observation["id"],
                            source_observation_updated_at=observation["updated_at"],
                            decision=draft.decision.value,
                            financial_account_id=financial_account_id,
                            movement_id=movement_id,
                            currency=observation["currency"],
                            movement_result_effect=movement_effect,
                            movement_role=movement_role,
                            decided_by_operator_id=operator_id,
                            decided_at=func.transaction_timestamp(),
                            idempotency_key=idempotency_key,
                            request_digest=request_digest,
                        )
                        .returning(*reconciled_transaction_ledger_links.c)
                    )
                    .mappings()
                    .one()
                )
                return _review_record(inserted)
        except (
            BankingLedgerReviewAccessError,
            BankingLedgerReviewConflictError,
            BankingLedgerReviewNotEligibleError,
            BankingLedgerReviewNotFoundError,
            BankingLedgerReviewPersistenceError,
        ):
            raise
        except FinancialMovementAccessError:
            raise BankingLedgerReviewAccessError(
                "banking ledger review access denied"
            ) from None
        except FinancialMovementAccountNotFoundError:
            raise BankingLedgerReviewNotFoundError(
                "financial account was not found"
            ) from None
        except FinancialMovementBeforeOpeningBalanceError:
            raise BankingLedgerReviewNotEligibleError(
                "reviewed transaction precedes the opening balance"
            ) from None
        except FinancialMovementIdempotencyConflictError:
            raise BankingLedgerReviewConflictError(
                "banking ledger review Movement idempotency conflict"
            ) from None
        except FinancialMovementPersistenceError:
            raise BankingLedgerReviewPersistenceError(
                "banking ledger review Movement could not be persisted"
            ) from None
        except IntegrityError as error:
            name = _constraint_name(error)
            if name in {
                "uq_banking_ledger_links_reconciled_decision",
                "uq_banking_ledger_links_idempotency",
            }:
                raise BankingLedgerReviewConflictError(
                    "banking ledger review decision conflict"
                ) from None
            raise BankingLedgerReviewPersistenceError(
                "banking ledger review decision could not be persisted"
            ) from None
        except DBAPIError:
            raise BankingLedgerReviewPersistenceError(
                "banking ledger review decision could not be persisted"
            ) from None


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


def _require_review_membership(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
) -> None:
    try:
        _require_active_membership(
            connection,
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
        )
    except FinancialMovementAccessError:
        raise BankingLedgerReviewAccessError(
            "banking ledger review access denied"
        ) from None


def _load_review_source(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    reconciled_transaction_id: UUID,
    lock: bool,
) -> tuple[RowMapping, RowMapping]:
    reconciled_query = select(reconciled_transactions).where(
        reconciled_transactions.c.id == reconciled_transaction_id,
        reconciled_transactions.c.residence_id == residence_id,
    )
    if lock:
        reconciled_query = reconciled_query.with_for_update()
    reconciled = connection.execute(reconciled_query).mappings().one_or_none()
    if reconciled is None:
        raise BankingLedgerReviewNotFoundError(
            "reconciled transaction was not found"
        )

    connection_scope = connection.scalar(
        select(connections.c.id).where(
            connections.c.id == reconciled["connection_id"],
            connections.c.installation_id == installation_id,
            connections.c.residence_id == residence_id,
        )
    )
    if connection_scope is None:
        raise BankingLedgerReviewNotFoundError(
            "reconciled transaction was not found"
        )

    observation_query = select(external_observations).where(
        external_observations.c.id == reconciled["source_observation_id"],
        external_observations.c.connection_id == reconciled["connection_id"],
        external_observations.c.residence_id == residence_id,
    )
    if lock:
        observation_query = observation_query.with_for_update(read=True)
    observation = connection.execute(observation_query).mappings().one_or_none()
    if observation is None:
        raise BankingLedgerReviewNotFoundError(
            "reconciled transaction source was not found"
        )
    return reconciled, observation


def _candidate(
    reconciled: RowMapping,
    observation: RowMapping,
) -> BankingLedgerReviewCandidate:
    try:
        return BankingLedgerReviewCandidate(
            reconciled_transaction_id=reconciled["id"],
            external_account_record_id=reconciled["external_account_record_id"],
            status=StoredTransactionObservationStatus(reconciled["status"]),
            effective_date=observation["effective_date"],
            amount=Decimal(observation["amount"]),
            currency=observation["currency"],
            description=observation["description"],
            source_observation_id=observation["id"],
            source_observation_updated_at=observation["updated_at"],
        )
    except (KeyError, TypeError, ValueError):
        raise BankingLedgerReviewPersistenceError(
            "banking ledger review candidate state is invalid"
        ) from None


def _require_source_snapshot(
    reconciled: RowMapping,
    observation: RowMapping,
    draft: BankingLedgerReviewDraft,
) -> None:
    if reconciled["source_observation_id"] != draft.source_observation_id:
        raise BankingLedgerReviewConflictError(
            "reviewed banking source changed; review again"
        )
    if observation["id"] != draft.source_observation_id:
        raise BankingLedgerReviewConflictError(
            "reviewed banking source changed; review again"
        )
    if observation["updated_at"] != draft.source_observation_updated_at:
        raise BankingLedgerReviewConflictError(
            "reviewed banking source changed; review again"
        )

    if draft.decision is not BankingLedgerReviewDecision.IGNORE:
        if (
            reconciled["status"]
            != StoredTransactionObservationStatus.CONFIRMED.value
            or observation["status"]
            != StoredTransactionObservationStatus.CONFIRMED.value
        ):
            raise BankingLedgerReviewNotEligibleError(
                "only confirmed banking transactions may enter the ledger"
            )


def _apply_decision(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
    idempotency_key: UUID,
    draft: BankingLedgerReviewDraft,
    reconciled: RowMapping,
    observation: RowMapping,
) -> tuple[UUID | None, UUID | None, str | None, str | None]:
    del reconciled
    if draft.decision is BankingLedgerReviewDecision.IGNORE:
        return None, None, None, None

    amount = Decimal(observation["amount"])
    currency = observation["currency"]
    if not amount.is_finite() or amount == 0:
        raise BankingLedgerReviewNotEligibleError(
            "banking transaction amount is not ledger-eligible"
        )

    if draft.decision is BankingLedgerReviewDecision.LINK_EXISTING_MOVEMENT:
        assert draft.movement_id is not None
        target = (
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
        if target is None:
            raise BankingLedgerReviewNotFoundError(
                "financial Movement was not found"
            )
        if target["currency"] != currency or Decimal(target["amount"]) != amount:
            raise BankingLedgerReviewConflictError(
                "financial Movement does not match reviewed amount and currency"
            )
        return (
            target["account_id"],
            target["id"],
            target["result_effect"],
            target["role"],
        )

    assert draft.financial_account_id is not None
    if draft.decision is BankingLedgerReviewDecision.IMPORT_AS_INCOME:
        if amount <= 0:
            raise BankingLedgerReviewNotEligibleError(
                "income import requires a positive reviewed amount"
            )
        effect = FinancialResultEffect.INCOME
    else:
        if amount >= 0:
            raise BankingLedgerReviewNotEligibleError(
                "expense import requires a negative reviewed amount"
            )
        effect = FinancialResultEffect.EXPENSE

    description = observation["description"] or _DEFAULT_DESCRIPTION
    if len(description) > 256:
        raise BankingLedgerReviewNotEligibleError(
            "banking transaction description exceeds ledger limits"
        )

    movement = _create_standard_movement(
        connection,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
        idempotency_key=_movement_idempotency_key(idempotency_key),
        draft=FinancialMovementDraft(
            account_id=draft.financial_account_id,
            amount=Money(amount, currency),
            result_effect=effect,
            effective_date=observation["effective_date"],
            competence_date=observation["effective_date"],
            description=description,
        ),
    )
    return (
        movement.account_id,
        movement.id,
        movement.result_effect.value,
        movement.role.value,
    )


def _create_standard_movement(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
    idempotency_key: UUID,
    draft: FinancialMovementDraft,
):
    """Compose the canonical Movement guards in an existing transaction."""
    request_digest = _standard_request_digest(operator_id, draft)
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
        return _require_movement_replay(existing, request_digest)

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

    inserted = (
        connection.execute(
            pg_insert(financial_movements)
            .values(
                id=new_financial_resource_id(),
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
        return _movement_record(inserted)

    raced = _movement_by_idempotency(
        connection,
        installation_id=installation_id,
        idempotency_key=idempotency_key,
    )
    if raced is None:
        raise FinancialMovementIdempotencyConflictError(
            "movement idempotency conflict"
        )
    return _require_movement_replay(raced, request_digest)


def _review_request_digest(
    *,
    operator_id: UUID,
    reconciled_transaction_id: UUID,
    draft: BankingLedgerReviewDraft,
) -> str:
    parts = (
        str(operator_id),
        str(reconciled_transaction_id),
        str(draft.source_observation_id),
        draft.source_observation_updated_at.isoformat(),
        draft.decision.value,
        str(draft.financial_account_id) if draft.financial_account_id else "",
        str(draft.movement_id) if draft.movement_id else "",
    )
    material = "\x1f".join((_REVIEW_DIGEST_NAMESPACE, *parts))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _movement_idempotency_key(review_idempotency_key: UUID) -> UUID:
    material = (
        f"{_MOVEMENT_KEY_NAMESPACE}\x1f{review_idempotency_key}"
    ).encode("utf-8")
    raw = bytearray(hashlib.sha256(material).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


def _link_by_idempotency(
    connection: Connection,
    *,
    installation_id: UUID,
    idempotency_key: UUID,
) -> RowMapping | None:
    return (
        connection.execute(
            select(reconciled_transaction_ledger_links).where(
                reconciled_transaction_ledger_links.c.installation_id
                == installation_id,
                reconciled_transaction_ledger_links.c.idempotency_key
                == idempotency_key,
            )
        )
        .mappings()
        .one_or_none()
    )


def _link_by_reconciled(
    connection: Connection,
    *,
    residence_id: UUID,
    connection_id: UUID,
    reconciled_transaction_id: UUID,
) -> RowMapping | None:
    return (
        connection.execute(
            select(reconciled_transaction_ledger_links).where(
                reconciled_transaction_ledger_links.c.residence_id == residence_id,
                reconciled_transaction_ledger_links.c.connection_id == connection_id,
                reconciled_transaction_ledger_links.c.reconciled_transaction_id
                == reconciled_transaction_id,
            )
        )
        .mappings()
        .one_or_none()
    )


def _require_review_replay(
    row: RowMapping,
    request_digest: str,
) -> BankingLedgerReviewRecord:
    if row["request_digest"] != request_digest:
        raise BankingLedgerReviewConflictError(
            "review idempotency key was reused for another request"
        )
    return _review_record(row)


def _review_record(row: RowMapping) -> BankingLedgerReviewRecord:
    try:
        return BankingLedgerReviewRecord(
            id=row["id"],
            reconciled_transaction_id=row["reconciled_transaction_id"],
            source_observation_id=row["source_observation_id"],
            source_observation_updated_at=row["source_observation_updated_at"],
            decision=BankingLedgerReviewDecision(row["decision"]),
            financial_account_id=row["financial_account_id"],
            movement_id=row["movement_id"],
            decided_by_operator_id=row["decided_by_operator_id"],
            decided_at=row["decided_at"],
        )
    except (KeyError, TypeError, ValueError):
        raise BankingLedgerReviewPersistenceError(
            "banking ledger review state is invalid"
        ) from None


def _constraint_name(error: IntegrityError) -> str | None:
    diagnostic = getattr(error.orig, "diag", None)
    value = getattr(diagnostic, "constraint_name", None)
    return value if isinstance(value, str) else None


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


__all__ = ["BankingLedgerReviewStore"]
