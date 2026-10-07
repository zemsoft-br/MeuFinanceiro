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
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from uuid import UUID

from meufinanceiro_finance import (
    RECURRENCE_GENERATION_MAX_MONTHS,
    RECURRENCE_LIST_MAX,
    RECURRENCE_OCCURRENCE_LIST_MAX,
    RECURRENCE_WINDOW_MAX_MONTHS,
    FinancialOccurrenceMovementState,
    FinancialOccurrenceStatus,
    FinancialRecurrenceDraft,
    FinancialRecurrenceEditOutcome,
    FinancialRecurrenceFrequency,
    FinancialRecurrenceGenerationResult,
    FinancialRecurrenceOccurrenceRecord,
    FinancialRecurrenceRealization,
    FinancialRecurrenceRecord,
    FinancialRecurrenceRealizationDraft,
    FinancialRecurrenceReplacement,
    FinancialRecurrenceStatus,
    FinancialRecurrenceWindow,
    FinancialResultEffect,
    Money,
    can_generate_occurrences,
    can_transition_occurrence,
    new_financial_idempotency_key,
    new_financial_resource_id,
    occurrence_manual_entry,
    occurrences_to_supersede,
    recurrence_replacement_changes_rule,
    scheduled_occurrences,
    validate_financial_idempotency_key,
    validate_financial_resource_id,
)
from sqlalchemy import Connection, Engine, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementAccessError,
    FinancialMovementAccountNotFoundError,
    FinancialMovementBeforeOpeningBalanceError,
    FinancialMovementPersistenceError,
    _owned_active_account_currency,
    _require_active_membership,
    _set_context,
    create_standard_movement_in_transaction,
)
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_recurrence_schema import (
    financial_recurrence_occurrences,
    financial_recurrences,
)

_REQUEST_DIGEST_NAMESPACE = "meufinanceiro:recurrence-create:v1"
_REALIZATION_DIGEST_NAMESPACE = "meufinanceiro:recurrence-realize:v1"


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


class FinancialRecurrenceOccurrenceNotFoundError(FinancialRecurrencePersistenceError):
    """Occurrence is missing or invisible to the actor (indistinguishable)."""


class FinancialRecurrenceOccurrenceStateError(FinancialRecurrencePersistenceError):
    """The occurrence is in a state that does not allow the requested command."""


class FinancialRecurrencePausedError(FinancialRecurrencePersistenceError):
    """A PAUSED recurrence does not generate occurrences."""


class FinancialRecurrenceBeforeOpeningBalanceError(FinancialRecurrencePersistenceError):
    """The realization would precede the account opening-balance anchor."""


class FinancialRecurrenceLimitError(FinancialRecurrencePersistenceError):
    """The visible set is at its cap: a list is never silently cut short."""


class FinancialRecurrenceStore:
    """Create, read, list, CAS-edit and run the planning lifecycle of recurrences."""

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

                visible_rules = connection.scalar(
                    select(func.count())
                    .select_from(rules)
                    .where(
                        rules.c.installation_id == installation_id,
                        rules.c.residence_id == residence_id,
                    )
                )
                if (visible_rules or 0) >= RECURRENCE_LIST_MAX:
                    raise FinancialRecurrenceLimitError("recurrence limit reached")
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
                            RECURRENCE_LIST_MAX + 1
                        )
                    )
                    .mappings()
                    .all()
                )
                if len(rows) > RECURRENCE_LIST_MAX:
                    raise FinancialRecurrenceLimitError("recurrence limit reached")
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
                # Serialize against generation, pause and other edits, then decide the
                # CAS on the locked row: what is current *now*.
                current = _locked_owned_rule(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    recurrence_id=recurrence_id,
                )
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

    def pause_recurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        recurrence_id: UUID,
    ) -> FinancialRecurrenceRecord:
        """PAUSED stops future generation; history is kept. Idempotent by state."""
        return self._set_status(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            recurrence_id=recurrence_id,
            target=FinancialRecurrenceStatus.PAUSED,
        )

    def resume_recurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        recurrence_id: UUID,
    ) -> FinancialRecurrenceRecord:
        """ACTIVE allows new generation again. It generates nothing by itself."""
        return self._set_status(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            recurrence_id=recurrence_id,
            target=FinancialRecurrenceStatus.ACTIVE,
        )

    def _set_status(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        recurrence_id: UUID,
        target: FinancialRecurrenceStatus,
    ) -> FinancialRecurrenceRecord:
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_resource_id(recurrence_id)
        rules = financial_recurrences
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                current = _locked_owned_rule(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    recurrence_id=recurrence_id,
                )
                if current["status"] == target.value:
                    return _record(current)
                updated = (
                    connection.execute(
                        update(rules)
                        .where(
                            rules.c.id == recurrence_id,
                            rules.c.installation_id == installation_id,
                            rules.c.residence_id == residence_id,
                            rules.c.owner_operator_id == operator_id,
                            rules.c.version == current["version"],
                        )
                        .values(
                            status=target.value,
                            version=current["version"] + 1,
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
                return _record(updated)
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

    def generate_occurrences(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        recurrence_id: UUID,
        window: FinancialRecurrenceWindow,
    ) -> FinancialRecurrenceGenerationResult:
        """Materialize the due months of a window as PENDING occurrences.

        Explicit, bounded and replay-safe: the rule row is locked for the call, the
        insert is ``ON CONFLICT DO NOTHING`` on the one-live-occurrence-per-month
        index, and repeating or racing the call converges on the same set. A PAUSED
        rule never generates (the database trigger refuses it too). Nothing here
        reads a clock, writes a Movement or touches a balance.
        """
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_resource_id(recurrence_id)
        if not isinstance(window, FinancialRecurrenceWindow):
            raise TypeError("window must be FinancialRecurrenceWindow")
        if window.months > RECURRENCE_GENERATION_MAX_MONTHS:
            raise FinancialRecurrenceInvalidShapeError(
                "generation window exceeds the allowed number of months"
            )
        occurrences = financial_recurrence_occurrences
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                row = _locked_owned_rule(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    recurrence_id=recurrence_id,
                )
                rule = _record(row)
                if not can_generate_occurrences(rule):
                    raise FinancialRecurrencePausedError("recurrence is paused")
                _owned_active_account(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    account_id=rule.account_id,
                )
                due = scheduled_occurrences(
                    start_date=rule.start_date,
                    day_of_month=rule.day_of_month,
                    end_date=rule.end_date,
                    window=window,
                )
                created = 0
                if due:
                    inserted = connection.execute(
                        pg_insert(occurrences)
                        .values(
                            [
                                {
                                    "id": new_financial_resource_id(),
                                    "installation_id": installation_id,
                                    "residence_id": residence_id,
                                    "recurrence_id": rule.id,
                                    "account_id": rule.account_id,
                                    "owner_operator_id": rule.owner_operator_id,
                                    "period_start": item.period_start,
                                    "scheduled_date": item.scheduled_date,
                                    "rule_version": rule.version,
                                    "result_effect": rule.result_effect.value,
                                    "currency": rule.expected.currency,
                                    "expected_amount": rule.expected.amount,
                                    "description": rule.description,
                                    "status": FinancialOccurrenceStatus.PENDING.value,
                                    "created_at": func.transaction_timestamp(),
                                    "updated_at": func.transaction_timestamp(),
                                }
                                for item in due
                            ]
                        )
                        .on_conflict_do_nothing(
                            index_elements=[
                                occurrences.c.recurrence_id,
                                occurrences.c.period_start,
                            ],
                            index_where=text("status <> 'SUPERSEDED'"),
                        )
                        .returning(occurrences.c.id)
                    )
                    created = len(inserted.all())
                live = _select_occurrences(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    window=window,
                    recurrence_id=rule.id,
                    status=None,
                )
                return FinancialRecurrenceGenerationResult(created, live)
        except FinancialMovementAccessError:
            raise FinancialRecurrenceAccessError("recurrence access denied") from None
        except FinancialRecurrencePersistenceError:
            raise
        except IntegrityError:
            raise FinancialRecurrenceConflictError("recurrence conflict") from None
        except DBAPIError:
            raise FinancialRecurrencePersistenceError(
                "occurrences could not be persisted"
            ) from None

    def list_occurrences(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        window: FinancialRecurrenceWindow,
        recurrence_id: UUID | None = None,
        status: FinancialOccurrenceStatus | None = None,
    ) -> tuple[FinancialRecurrenceOccurrenceRecord, ...]:
        """Visible occurrences of a bounded month window.

        SUPERSEDED rows are history and only appear when asked for by status.
        """
        _require_scope(installation_id, residence_id, operator_id)
        if not isinstance(window, FinancialRecurrenceWindow):
            raise TypeError("window must be FinancialRecurrenceWindow")
        if window.months > RECURRENCE_WINDOW_MAX_MONTHS:
            raise FinancialRecurrenceInvalidShapeError(
                "occurrence window exceeds the allowed number of months"
            )
        if recurrence_id is not None:
            validate_financial_resource_id(recurrence_id)
        if status is not None and not isinstance(status, FinancialOccurrenceStatus):
            raise TypeError("status must be FinancialOccurrenceStatus")
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                if (
                    recurrence_id is not None
                    and _visible_row(
                        connection, installation_id, residence_id, recurrence_id
                    )
                    is None
                ):
                    raise FinancialRecurrenceNotFoundError("recurrence was not found")
                return _select_occurrences(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    window=window,
                    recurrence_id=recurrence_id,
                    status=status,
                )
        except FinancialMovementAccessError:
            raise FinancialRecurrenceAccessError("recurrence access denied") from None
        except FinancialRecurrencePersistenceError:
            raise
        except DBAPIError:
            raise FinancialRecurrencePersistenceError(
                "occurrences could not be read"
            ) from None

    def get_occurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        occurrence_id: UUID,
    ) -> FinancialRecurrenceOccurrenceRecord:
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_resource_id(occurrence_id)
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                row = _visible_occurrence_row(
                    connection, installation_id, residence_id, occurrence_id
                )
                if row is None:
                    raise FinancialRecurrenceOccurrenceNotFoundError(
                        "recurrence occurrence was not found"
                    )
                return _load_occurrences(connection, [row])[0]
        except FinancialMovementAccessError:
            raise FinancialRecurrenceAccessError("recurrence access denied") from None
        except FinancialRecurrencePersistenceError:
            raise
        except DBAPIError:
            raise FinancialRecurrencePersistenceError(
                "occurrence could not be read"
            ) from None

    def skip_occurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        occurrence_id: UUID,
    ) -> FinancialRecurrenceOccurrenceRecord:
        """PENDING -> SKIPPED. Idempotent; REALIZED and SUPERSEDED fail closed."""
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_resource_id(occurrence_id)
        occurrences = financial_recurrence_occurrences
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                current = _locked_owned_occurrence(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    occurrence_id=occurrence_id,
                )
                status = FinancialOccurrenceStatus(current["status"])
                if status is FinancialOccurrenceStatus.SKIPPED:
                    return _load_occurrences(connection, [current])[0]
                if not can_transition_occurrence(
                    status, FinancialOccurrenceStatus.SKIPPED
                ):
                    raise FinancialRecurrenceOccurrenceStateError(
                        "recurrence occurrence cannot be skipped"
                    )
                updated = (
                    connection.execute(
                        update(occurrences)
                        .where(
                            occurrences.c.id == occurrence_id,
                            occurrences.c.status
                            == FinancialOccurrenceStatus.PENDING.value,
                        )
                        .values(
                            status=FinancialOccurrenceStatus.SKIPPED.value,
                            skipped_at=func.transaction_timestamp(),
                            updated_at=func.transaction_timestamp(),
                        )
                        .returning(*occurrences.c)
                    )
                    .mappings()
                    .one_or_none()
                )
                if updated is None:
                    raise FinancialRecurrenceOccurrenceStateError(
                        "recurrence occurrence cannot be skipped"
                    )
                return _load_occurrences(connection, [updated])[0]
        except FinancialMovementAccessError:
            raise FinancialRecurrenceAccessError("recurrence access denied") from None
        except FinancialRecurrencePersistenceError:
            raise
        except IntegrityError:
            raise FinancialRecurrenceConflictError("recurrence conflict") from None
        except DBAPIError:
            raise FinancialRecurrencePersistenceError(
                "occurrence could not be persisted"
            ) from None

    def realize_occurrence(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        occurrence_id: UUID,
        idempotency_key: UUID,
        draft: FinancialRecurrenceRealizationDraft,
    ) -> FinancialRecurrenceOccurrenceRecord:
        """Turn one PENDING occurrence into exactly one canonical Movement.

        One transaction, in this order: lock the occurrence, replay, revalidate,
        write the Movement through the canonical writer
        (``create_standard_movement_in_transaction``) and link it. Any failure rolls
        the whole transaction back, so there is never a Movement without its link
        nor a link without its Movement. The same key with the same material
        converges on the same Movement; anything else fails closed. No category or
        allocation is decided here.
        """
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_resource_id(occurrence_id)
        validate_financial_idempotency_key(idempotency_key)
        if not isinstance(draft, FinancialRecurrenceRealizationDraft):
            raise TypeError("draft must be FinancialRecurrenceRealizationDraft")

        request_digest = _realization_digest(operator_id, occurrence_id, draft)
        occurrences = financial_recurrence_occurrences
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                current = _locked_owned_occurrence(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    occurrence_id=occurrence_id,
                )
                if current["realization_idempotency_key"] == idempotency_key:
                    if current["realization_request_digest"] != request_digest:
                        raise FinancialRecurrenceConflictError(
                            "recurrence realization idempotency conflict"
                        )
                    return _load_occurrences(connection, [current])[0]
                key_owner = connection.scalar(
                    select(occurrences.c.id).where(
                        occurrences.c.installation_id == installation_id,
                        occurrences.c.realization_idempotency_key == idempotency_key,
                    )
                )
                if key_owner is not None:
                    raise FinancialRecurrenceConflictError(
                        "recurrence realization idempotency conflict"
                    )
                if current["status"] != FinancialOccurrenceStatus.PENDING.value:
                    raise FinancialRecurrenceOccurrenceStateError(
                        "recurrence occurrence cannot be realized"
                    )

                rule_row = _visible_row(
                    connection,
                    installation_id,
                    residence_id,
                    current["recurrence_id"],
                )
                if (
                    rule_row is None
                    or rule_row["owner_operator_id"] != operator_id
                    or rule_row["account_id"] != current["account_id"]
                    or rule_row["currency"] != current["currency"]
                ):
                    raise FinancialRecurrenceOccurrenceNotFoundError(
                        "recurrence occurrence was not found"
                    )
                account_currency = _owned_active_account(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    account_id=current["account_id"],
                )
                if account_currency != current["currency"]:
                    raise FinancialRecurrenceAccountNotFoundError(
                        "financial account was not found"
                    )
                try:
                    entry = occurrence_manual_entry(
                        occurrence=_occurrence_record(current), draft=draft
                    )
                except (TypeError, ValueError):
                    raise FinancialRecurrenceInvalidShapeError(
                        "realization does not fit the occurrence"
                    ) from None

                try:
                    movement = create_standard_movement_in_transaction(
                        connection,
                        installation_id=installation_id,
                        residence_id=residence_id,
                        operator_id=operator_id,
                        # A fresh key of its own: a realization key never adopts a
                        # Movement that already exists under that key.
                        idempotency_key=new_financial_idempotency_key(),
                        draft=entry.to_movement_draft(),
                    )
                except FinancialMovementAccessError:
                    raise FinancialRecurrenceAccessError(
                        "recurrence access denied"
                    ) from None
                except FinancialMovementAccountNotFoundError:
                    raise FinancialRecurrenceAccountNotFoundError(
                        "financial account was not found"
                    ) from None
                except FinancialMovementBeforeOpeningBalanceError:
                    raise FinancialRecurrenceBeforeOpeningBalanceError(
                        "financial operation precedes opening balance"
                    ) from None
                except FinancialMovementPersistenceError:
                    # Anything else the canonical writer refuses stays sanitized.
                    raise FinancialRecurrencePersistenceError(
                        "occurrence could not be realized"
                    ) from None
                updated = _link_occurrence_to_movement(
                    connection,
                    occurrence_id=occurrence_id,
                    operator_id=operator_id,
                    movement_id=movement.id,
                    idempotency_key=idempotency_key,
                    request_digest=request_digest,
                )
                return _load_occurrences(connection, [updated])[0]
        except FinancialMovementAccessError:
            raise FinancialRecurrenceAccessError("recurrence access denied") from None
        except FinancialRecurrencePersistenceError:
            raise
        except IntegrityError as error:
            raise _realization_integrity_error(error) from None
        except DBAPIError:
            raise FinancialRecurrencePersistenceError(
                "occurrence could not be realized"
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


def _locked_owned_rule(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
    recurrence_id: UUID,
) -> RowMapping:
    """Visible -> owned -> locked. Missing and invisible are the same error."""
    visible = _visible_row(connection, installation_id, residence_id, recurrence_id)
    if visible is None:
        raise FinancialRecurrenceNotFoundError("recurrence was not found")
    if visible["owner_operator_id"] != operator_id:
        raise FinancialRecurrenceNotEditableError("recurrence is read-only")
    locked = _visible_row(
        connection, installation_id, residence_id, recurrence_id, lock=True
    )
    if locked is None:
        raise FinancialRecurrenceNotFoundError("recurrence was not found")
    return locked


def _visible_occurrence_row(
    connection: Connection,
    installation_id: UUID,
    residence_id: UUID,
    occurrence_id: UUID,
    *,
    lock: bool = False,
) -> RowMapping | None:
    occurrences = financial_recurrence_occurrences
    statement = select(occurrences).where(
        occurrences.c.id == occurrence_id,
        occurrences.c.installation_id == installation_id,
        occurrences.c.residence_id == residence_id,
    )
    if lock:
        statement = statement.with_for_update()
    return connection.execute(statement).mappings().one_or_none()


def _locked_owned_occurrence(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
    occurrence_id: UUID,
) -> RowMapping:
    visible = _visible_occurrence_row(
        connection, installation_id, residence_id, occurrence_id
    )
    if visible is None:
        raise FinancialRecurrenceOccurrenceNotFoundError(
            "recurrence occurrence was not found"
        )
    if visible["owner_operator_id"] != operator_id:
        raise FinancialRecurrenceNotEditableError("recurrence occurrence is read-only")
    locked = _visible_occurrence_row(
        connection, installation_id, residence_id, occurrence_id, lock=True
    )
    if locked is None:
        raise FinancialRecurrenceOccurrenceNotFoundError(
            "recurrence occurrence was not found"
        )
    return locked


def _select_occurrences(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    window: FinancialRecurrenceWindow,
    recurrence_id: UUID | None,
    status: FinancialOccurrenceStatus | None,
) -> tuple[FinancialRecurrenceOccurrenceRecord, ...]:
    occurrences = financial_recurrence_occurrences
    statement = select(occurrences).where(
        occurrences.c.installation_id == installation_id,
        occurrences.c.residence_id == residence_id,
        occurrences.c.period_start >= window.from_period,
        occurrences.c.period_start <= window.through_period,
    )
    if recurrence_id is not None:
        statement = statement.where(occurrences.c.recurrence_id == recurrence_id)
    if status is None:
        statement = statement.where(
            occurrences.c.status != FinancialOccurrenceStatus.SUPERSEDED.value
        )
    else:
        statement = statement.where(occurrences.c.status == status.value)
    rows = (
        connection.execute(
            statement.order_by(
                occurrences.c.period_start,
                occurrences.c.scheduled_date,
                occurrences.c.recurrence_id,
                occurrences.c.created_at,
                occurrences.c.id,
            ).limit(RECURRENCE_OCCURRENCE_LIST_MAX + 1)
        )
        .mappings()
        .all()
    )
    if len(rows) > RECURRENCE_OCCURRENCE_LIST_MAX:
        raise FinancialRecurrenceLimitError("recurrence limit reached")
    return _load_occurrences(connection, rows)


def _load_occurrences(
    connection: Connection, rows: Sequence[RowMapping]
) -> tuple[FinancialRecurrenceOccurrenceRecord, ...]:
    """Occurrences with the realized side read from the linked Movement.

    Two statements for any number of rows: the linked Movements and the ids among
    them that have been reversed. The state of the link is *derived*; nothing here
    reopens or rewrites an occurrence.
    """
    movement_ids = [
        row["movement_id"] for row in rows if row["movement_id"] is not None
    ]
    movements: dict[UUID, RowMapping] = {}
    reversed_ids: set[UUID] = set()
    if movement_ids:
        movements = {
            row["id"]: row
            for row in connection.execute(
                select(financial_movements).where(
                    financial_movements.c.id.in_(movement_ids)
                )
            )
            .mappings()
            .all()
        }
        reversed_ids = set(
            connection.scalars(
                select(financial_movements.c.reversal_of_id).where(
                    financial_movements.c.reversal_of_id.in_(movement_ids)
                )
            ).all()
        )
    return tuple(
        _occurrence_record(row, _realization(row, movements, reversed_ids))
        for row in rows
    )


def _realization(
    row: RowMapping, movements: dict[UUID, RowMapping], reversed_ids: set[UUID]
) -> FinancialRecurrenceRealization | None:
    movement_id = row["movement_id"]
    if movement_id is None:
        return None
    movement = movements.get(movement_id)
    if movement is None:
        raise FinancialRecurrencePersistenceError(
            "recurrence occurrence state is invalid"
        )
    try:
        return FinancialRecurrenceRealization(
            movement_id=movement_id,
            actual=Money(abs(Decimal(movement["amount"])), movement["currency"]),
            effective_date=movement["effective_date"],
            competence_date=movement["competence_date"],
            realized_at=row["realized_at"],
            movement_state=(
                FinancialOccurrenceMovementState.REVERSED
                if movement_id in reversed_ids
                else FinancialOccurrenceMovementState.ACTIVE
            ),
        )
    except (KeyError, TypeError, ValueError):
        raise FinancialRecurrencePersistenceError(
            "recurrence occurrence state is invalid"
        ) from None


def _realization_digest(
    operator_id: UUID,
    occurrence_id: UUID,
    draft: FinancialRecurrenceRealizationDraft,
) -> str:
    material = json.dumps(
        [
            _REALIZATION_DIGEST_NAMESPACE,
            str(operator_id),
            str(occurrence_id),
            draft.canonical_material(),
        ],
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _link_occurrence_to_movement(
    connection: Connection,
    *,
    occurrence_id: UUID,
    operator_id: UUID,
    movement_id: UUID,
    idempotency_key: UUID,
    request_digest: str,
) -> RowMapping:
    """PENDING -> REALIZED with the Movement written in this very transaction."""
    occurrences = financial_recurrence_occurrences
    updated = (
        connection.execute(
            update(occurrences)
            .where(
                occurrences.c.id == occurrence_id,
                occurrences.c.status == FinancialOccurrenceStatus.PENDING.value,
            )
            .values(
                status=FinancialOccurrenceStatus.REALIZED.value,
                movement_id=movement_id,
                realization_idempotency_key=idempotency_key,
                realization_request_digest=request_digest,
                realized_at=func.transaction_timestamp(),
                realized_by_operator_id=operator_id,
                updated_at=func.transaction_timestamp(),
            )
            .returning(*occurrences.c)
        )
        .mappings()
        .one_or_none()
    )
    if updated is None:
        raise FinancialRecurrenceOccurrenceStateError(
            "recurrence occurrence cannot be realized"
        )
    return updated


def _realization_integrity_error(
    error: IntegrityError,
) -> FinancialRecurrencePersistenceError:
    diagnostic = getattr(error.orig, "diag", None)
    name = getattr(diagnostic, "constraint_name", None)
    if name in {
        "uq_finance_recurrence_occurrences_realization_key",
        "uq_finance_recurrence_occurrences_movement",
    }:
        return FinancialRecurrenceConflictError(
            "recurrence realization idempotency conflict"
        )
    return FinancialRecurrencePersistenceError("occurrence could not be realized")


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


def _occurrence_record(
    row: RowMapping, realization: FinancialRecurrenceRealization | None = None
) -> FinancialRecurrenceOccurrenceRecord:
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
            realization=realization,
        )
    except (KeyError, TypeError, ValueError):
        raise FinancialRecurrencePersistenceError(
            "recurrence occurrence state is invalid"
        ) from None


__all__ = [
    "FinancialRecurrenceAccessError",
    "FinancialRecurrenceAccountNotFoundError",
    "FinancialRecurrenceBeforeOpeningBalanceError",
    "FinancialRecurrenceConflictError",
    "FinancialRecurrenceInvalidShapeError",
    "FinancialRecurrenceLimitError",
    "FinancialRecurrenceNotEditableError",
    "FinancialRecurrenceNotFoundError",
    "FinancialRecurrenceOccurrenceNotFoundError",
    "FinancialRecurrenceOccurrenceStateError",
    "FinancialRecurrencePausedError",
    "FinancialRecurrencePersistenceError",
    "FinancialRecurrenceStore",
    "FinancialRecurrenceVersionConflictError",
]
