"""Residence/operator-aware persistence for manual monthly recurrences.

Recurrences are planning. This module never writes a Movement unless an operator
explicitly realizes one occurrence, and then it does so through the canonical
Movement writer inside the same transaction that links the occurrence (ADR-0027).
Create is replay-safe through an explicit idempotency key; edit is a compare-and-swap
on ``version`` that supersedes stale *future* PENDING occurrences explicitly and never
deletes anything. Authorization is double-checked: the store verifies what it can
explain, forced RLS and database triggers decide the rest.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from uuid import UUID

from meufinanceiro_finance import (
    RECURRENCE_LIST_MAX,
    FinancialOccurrenceStatus,
    FinancialRecurrenceDraft,
    FinancialRecurrenceEditOutcome,
    FinancialRecurrenceFrequency,
    FinancialRecurrenceOccurrenceRecord,
    FinancialRecurrenceRecord,
    FinancialRecurrenceReplacement,
    FinancialRecurrenceStatus,
    FinancialResultEffect,
    Money,
    new_financial_resource_id,
    occurrences_to_supersede,
    recurrence_replacement_changes_rule,
    validate_financial_idempotency_key,
    validate_financial_resource_id,
)
from sqlalchemy import Connection, Engine, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementAccessError,
    FinancialMovementAccountNotFoundError,
    _owned_active_account_currency,
    _require_active_membership,
    _set_context,
)
from meufinanceiro_persistence.financial_recurrence_schema import (
    financial_recurrence_occurrences,
    financial_recurrences,
)

_REQUEST_DIGEST_NAMESPACE = "meufinanceiro:recurrence-create:v1"


class FinancialRecurrencePersistenceError(RuntimeError):
    """Sanitized persistence failure for recurrence operations."""


class FinancialRecurrenceAccessError(FinancialRecurrencePersistenceError):
    """Actor has no active membership in the requested residence."""


class FinancialRecurrenceNotFoundError(FinancialRecurrencePersistenceError):
    """Recurrence is missing or invisible to the actor (indistinguishable)."""


class FinancialRecurrenceNotEditableError(FinancialRecurrencePersistenceError):
    """Recurrence is visible but the actor is not its owner."""


class FinancialRecurrenceAccountNotFoundError(FinancialRecurrencePersistenceError):
    """Account is missing, invisible, inactive, not owned or in another currency."""


class FinancialRecurrenceInvalidShapeError(FinancialRecurrencePersistenceError):
    """The request is well-typed but contradicts the stored recurrence identity."""


class FinancialRecurrenceConflictError(FinancialRecurrencePersistenceError):
    """An idempotency key was reused with other material."""


class FinancialRecurrenceVersionConflictError(FinancialRecurrencePersistenceError):
    """``expectedVersion`` is stale: the rule changed since the caller read it."""


class FinancialRecurrenceStore:
    """Create, read, list and CAS-edit manual monthly recurrences."""

    def __init__(self, engine: Engine) -> None:
        if not isinstance(engine, Engine):
            raise TypeError("engine must be SQLAlchemy Engine")
        self._engine = engine

    def create_recurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialRecurrenceDraft,
    ) -> FinancialRecurrenceRecord:
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_idempotency_key(idempotency_key)
        if not isinstance(draft, FinancialRecurrenceDraft):
            raise TypeError("draft must be FinancialRecurrenceDraft")

        request_digest = _create_digest(operator_id, draft)
        rules = financial_recurrences
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                existing = _by_idempotency(connection, installation_id, idempotency_key)
                if existing is not None:
                    return _replay(existing, request_digest)

                account_currency = _owned_active_account(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    account_id=draft.account_id,
                )
                if account_currency != draft.expected.currency:
                    raise FinancialRecurrenceAccountNotFoundError(
                        "financial account was not found"
                    )
                inserted = (
                    connection.execute(
                        pg_insert(rules)
                        .values(
                            id=new_financial_resource_id(),
                            installation_id=installation_id,
                            residence_id=residence_id,
                            account_id=draft.account_id,
                            owner_operator_id=operator_id,
                            description=draft.description,
                            result_effect=draft.result_effect.value,
                            currency=draft.expected.currency,
                            expected_amount=draft.expected.amount,
                            frequency=FinancialRecurrenceFrequency.MONTHLY.value,
                            start_date=draft.start_date,
                            day_of_month=draft.day_of_month,
                            end_date=draft.end_date,
                            status=FinancialRecurrenceStatus.ACTIVE.value,
                            version=1,
                            idempotency_key=idempotency_key,
                            request_digest=request_digest,
                            updated_by_operator_id=operator_id,
                            created_at=func.transaction_timestamp(),
                            updated_at=func.transaction_timestamp(),
                        )
                        .on_conflict_do_nothing(
                            index_elements=[
                                rules.c.installation_id,
                                rules.c.idempotency_key,
                            ]
                        )
                        .returning(*rules.c)
                    )
                    .mappings()
                    .one_or_none()
                )
                if inserted is None:
                    raced = _by_idempotency(
                        connection, installation_id, idempotency_key
                    )
                    if raced is not None:
                        return _replay(raced, request_digest)
                    raise FinancialRecurrenceConflictError("recurrence conflict")
                return _record(inserted)
        except FinancialMovementAccessError:
            raise FinancialRecurrenceAccessError("recurrence access denied") from None
        except FinancialRecurrencePersistenceError:
            raise
        except IntegrityError:
            raise FinancialRecurrenceConflictError("recurrence conflict") from None
        except DBAPIError:
            raise FinancialRecurrencePersistenceError(
                "recurrence could not be persisted"
            ) from None

    def get_recurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        recurrence_id: UUID,
    ) -> FinancialRecurrenceRecord:
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_resource_id(recurrence_id)
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                row = _visible_row(
                    connection, installation_id, residence_id, recurrence_id
                )
                if row is None:
                    raise FinancialRecurrenceNotFoundError("recurrence was not found")
                return _record(row)
        except FinancialMovementAccessError:
            raise FinancialRecurrenceAccessError("recurrence access denied") from None
        except FinancialRecurrencePersistenceError:
            raise
        except DBAPIError:
            raise FinancialRecurrencePersistenceError(
                "recurrence could not be read"
            ) from None

    def list_recurrences(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        status: FinancialRecurrenceStatus | None = None,
    ) -> tuple[FinancialRecurrenceRecord, ...]:
        """Visible rules, oldest first, hard-capped (no unbounded read)."""
        _require_scope(installation_id, residence_id, operator_id)
        if status is not None and not isinstance(status, FinancialRecurrenceStatus):
            raise TypeError("status must be FinancialRecurrenceStatus")
        rules = financial_recurrences
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                statement = select(rules).where(
                    rules.c.installation_id == installation_id,
                    rules.c.residence_id == residence_id,
                )
                if status is not None:
                    statement = statement.where(rules.c.status == status.value)
                rows = (
                    connection.execute(
                        statement.order_by(rules.c.created_at, rules.c.id).limit(
                            RECURRENCE_LIST_MAX
                        )
                    )
                    .mappings()
                    .all()
                )
                return tuple(_record(row) for row in rows)
        except FinancialMovementAccessError:
            raise FinancialRecurrenceAccessError("recurrence access denied") from None
        except FinancialRecurrencePersistenceError:
            raise
        except DBAPIError:
            raise FinancialRecurrencePersistenceError(
                "recurrences could not be read"
            ) from None

    def replace_recurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        recurrence_id: UUID,
        replacement: FinancialRecurrenceReplacement,
        today: date,
    ) -> FinancialRecurrenceEditOutcome:
        """Edit the mutable part iff ``expected_version`` is still current (CAS).

        A stale version raises ``FinancialRecurrenceVersionConflictError`` and writes
        nothing. An edit that changes nothing writes nothing either. Otherwise the
        version advances by one and every *future* PENDING occurrence (scheduled on
        or after ``today``) the new revision no longer describes becomes SUPERSEDED
        in the same transaction: nothing is silently reinterpreted and REALIZED /
        SKIPPED / overdue PENDING history is never touched.
        """
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_resource_id(recurrence_id)
        if not isinstance(replacement, FinancialRecurrenceReplacement):
            raise TypeError("replacement must be FinancialRecurrenceReplacement")
        if isinstance(today, bool) or not isinstance(today, date):
            raise TypeError("today must be date")
        rules = financial_recurrences
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                visible = _visible_row(
                    connection, installation_id, residence_id, recurrence_id
                )
                if visible is None:
                    raise FinancialRecurrenceNotFoundError("recurrence was not found")
                if visible["owner_operator_id"] != operator_id:
                    raise FinancialRecurrenceNotEditableError("recurrence is read-only")
                # Serialize against generation, pause and other edits, then re-read
                # the locked row: the CAS decides on what is current *now*.
                current = _visible_row(
                    connection,
                    installation_id,
                    residence_id,
                    recurrence_id,
                    lock=True,
                )
                if current is None:
                    raise FinancialRecurrenceNotFoundError("recurrence was not found")
                if current["version"] != replacement.expected_version:
                    raise FinancialRecurrenceVersionConflictError(
                        "recurrence version is stale"
                    )
                record = _record(current)
                if (
                    replacement.end_date is not None
                    and replacement.end_date < record.start_date
                ):
                    raise FinancialRecurrenceInvalidShapeError(
                        "end_date must not precede start_date"
                    )
                if not recurrence_replacement_changes_rule(
                    recurrence=record, replacement=replacement
                ):
                    return FinancialRecurrenceEditOutcome(record, 0)

                updated = (
                    connection.execute(
                        update(rules)
                        .where(
                            rules.c.id == recurrence_id,
                            rules.c.installation_id == installation_id,
                            rules.c.residence_id == residence_id,
                            rules.c.owner_operator_id == operator_id,
                            rules.c.version == replacement.expected_version,
                        )
                        .values(
                            description=replacement.description,
                            expected_amount=replacement.expected_amount,
                            day_of_month=replacement.day_of_month,
                            end_date=replacement.end_date,
                            version=replacement.expected_version + 1,
                            updated_at=func.transaction_timestamp(),
                            updated_by_operator_id=operator_id,
                        )
                        .returning(*rules.c)
                    )
                    .mappings()
                    .one_or_none()
                )
                if updated is None:
                    raise FinancialRecurrenceVersionConflictError(
                        "recurrence version is stale"
                    )
                superseded = _supersede_stale_future_pending(
                    connection,
                    recurrence_id=recurrence_id,
                    today=today,
                    replacement=replacement,
                )
                return FinancialRecurrenceEditOutcome(_record(updated), superseded)
        except FinancialMovementAccessError:
            raise FinancialRecurrenceAccessError("recurrence access denied") from None
        except FinancialRecurrencePersistenceError:
            raise
        except IntegrityError:
            raise FinancialRecurrenceConflictError("recurrence conflict") from None
        except DBAPIError:
            raise FinancialRecurrencePersistenceError(
                "recurrence could not be persisted"
            ) from None


def _require_scope(
    installation_id: UUID, residence_id: UUID, operator_id: UUID
) -> None:
    for name, value in (
        ("installation_id", installation_id),
        ("residence_id", residence_id),
        ("operator_id", operator_id),
    ):
        if not isinstance(value, UUID):
            raise TypeError(f"{name} must be UUID")


def _prepare(
    connection: Connection,
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


def _owned_active_account(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
    account_id: UUID,
) -> str:
    try:
        return _owned_active_account_currency(
            connection,
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )
    except FinancialMovementAccountNotFoundError:
        raise FinancialRecurrenceAccountNotFoundError(
            "financial account was not found"
        ) from None


def _create_digest(operator_id: UUID, draft: FinancialRecurrenceDraft) -> str:
    material = json.dumps(
        [_REQUEST_DIGEST_NAMESPACE, str(operator_id), draft.canonical_material()],
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _replay(row: RowMapping, request_digest: str) -> FinancialRecurrenceRecord:
    if row["request_digest"] != request_digest:
        raise FinancialRecurrenceConflictError("recurrence idempotency conflict")
    return _record(row)


def _by_idempotency(
    connection: Connection, installation_id: UUID, idempotency_key: UUID
) -> RowMapping | None:
    rules = financial_recurrences
    return (
        connection.execute(
            select(rules).where(
                rules.c.installation_id == installation_id,
                rules.c.idempotency_key == idempotency_key,
            )
        )
        .mappings()
        .one_or_none()
    )


def _visible_row(
    connection: Connection,
    installation_id: UUID,
    residence_id: UUID,
    recurrence_id: UUID,
    *,
    lock: bool = False,
) -> RowMapping | None:
    rules = financial_recurrences
    statement = select(rules).where(
        rules.c.id == recurrence_id,
        rules.c.installation_id == installation_id,
        rules.c.residence_id == residence_id,
    )
    if lock:
        statement = statement.with_for_update()
    return connection.execute(statement).mappings().one_or_none()


def _supersede_stale_future_pending(
    connection: Connection,
    *,
    recurrence_id: UUID,
    today: date,
    replacement: FinancialRecurrenceReplacement,
) -> int:
    occurrences = financial_recurrence_occurrences
    rows = (
        connection.execute(
            select(occurrences)
            .where(
                occurrences.c.recurrence_id == recurrence_id,
                occurrences.c.status == FinancialOccurrenceStatus.PENDING.value,
                occurrences.c.scheduled_date >= today,
            )
            .order_by(occurrences.c.scheduled_date, occurrences.c.id)
            .with_for_update()
        )
        .mappings()
        .all()
    )
    stale = occurrences_to_supersede(
        pending=[_occurrence_record(row) for row in rows],
        today=today,
        description=replacement.description,
        expected_amount=replacement.expected_amount,
        day_of_month=replacement.day_of_month,
        end_date=replacement.end_date,
    )
    if not stale:
        return 0
    result = connection.execute(
        update(occurrences)
        .where(
            occurrences.c.id.in_([occurrence.id for occurrence in stale]),
            occurrences.c.status == FinancialOccurrenceStatus.PENDING.value,
        )
        .values(
            status=FinancialOccurrenceStatus.SUPERSEDED.value,
            superseded_at=func.transaction_timestamp(),
            updated_at=func.transaction_timestamp(),
        )
    )
    return int(result.rowcount)


def _record(row: RowMapping) -> FinancialRecurrenceRecord:
    try:
        return FinancialRecurrenceRecord(
            id=row["id"],
            residence_id=row["residence_id"],
            account_id=row["account_id"],
            owner_operator_id=row["owner_operator_id"],
            description=row["description"],
            result_effect=FinancialResultEffect(row["result_effect"]),
            expected=Money(row["expected_amount"], row["currency"]),
            frequency=FinancialRecurrenceFrequency(row["frequency"]),
            start_date=row["start_date"],
            day_of_month=row["day_of_month"],
            end_date=row["end_date"],
            status=FinancialRecurrenceStatus(row["status"]),
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    except (KeyError, TypeError, ValueError):
        raise FinancialRecurrencePersistenceError(
            "recurrence state is invalid"
        ) from None


def _occurrence_record(row: RowMapping) -> FinancialRecurrenceOccurrenceRecord:
    """Occurrence without realization detail (callers only need PENDING rows)."""
    try:
        return FinancialRecurrenceOccurrenceRecord(
            id=row["id"],
            residence_id=row["residence_id"],
            recurrence_id=row["recurrence_id"],
            account_id=row["account_id"],
            owner_operator_id=row["owner_operator_id"],
            period_start=row["period_start"],
            scheduled_date=row["scheduled_date"],
            rule_version=row["rule_version"],
            result_effect=FinancialResultEffect(row["result_effect"]),
            expected=Money(Decimal(row["expected_amount"]), row["currency"]),
            description=row["description"],
            status=FinancialOccurrenceStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    except (KeyError, TypeError, ValueError):
        raise FinancialRecurrencePersistenceError(
            "recurrence occurrence state is invalid"
        ) from None


__all__ = [
    "FinancialRecurrenceAccessError",
    "FinancialRecurrenceAccountNotFoundError",
    "FinancialRecurrenceConflictError",
    "FinancialRecurrenceInvalidShapeError",
    "FinancialRecurrenceNotEditableError",
    "FinancialRecurrenceNotFoundError",
    "FinancialRecurrencePersistenceError",
    "FinancialRecurrenceStore",
    "FinancialRecurrenceVersionConflictError",
]
