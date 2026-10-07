"""Residence/operator-aware persistence for assisted recurrence suggestions (ADR-0028).

A suggestion is *derived*: this module reads realized, visible ``STANDARD EXPENSE``
Movements under forced RLS (so a Movement the operator cannot see never reaches the
grouping), runs the pure detector from ``meufinanceiro_finance`` and never writes on
read. The only writes are the operator's explicit decisions:

* ``dismiss`` records a personal, append-only ``DISMISSED`` decision;
* ``accept`` creates the canonical recurrence (the #254 writer, on this very
  transaction) and the ``ACCEPTED`` provenance atomically. Zero Movements and zero
  occurrences are ever written.

Both commands re-run the detector for the caller: a fingerprint is only an identity
the server recomputes, never an authority, so a stale, forged or invisible one is the
same sanitized "not available". Each call is a fixed number of statements, none of
them per Movement, account or recurrence.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from meufinanceiro_finance import (
    SUGGESTION_LIST_MAX,
    SUGGESTION_SCAN_MAX,
    FinancialRecurrenceObservation,
    FinancialRecurrenceRecord,
    FinancialRecurrenceRuleKey,
    FinancialRecurrenceSuggestion,
    FinancialRecurrenceSuggestionAcceptance,
    FinancialRecurrenceSuggestionDecision,
    FinancialRecurrenceSuggestionDecisionRecord,
    FinancialResultEffect,
    RECURRENCE_LIST_MAX,
    detect_recurrence_suggestions,
    new_financial_resource_id,
    recurrence_suggestion_window,
    validate_financial_idempotency_key,
    validate_recurrence_suggestion_fingerprint,
)
from meufinanceiro_finance.movements import FinancialMovementRole
from sqlalchemy import Connection, Engine, Select, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementAccessError,
)
from meufinanceiro_persistence.financial_recurrence_schema import (
    financial_recurrence_occurrences,
    financial_recurrences,
)
from meufinanceiro_persistence.financial_recurrence_store import (
    FinancialRecurrenceAccessError,
    FinancialRecurrenceConflictError,
    FinancialRecurrencePersistenceError,
    _create_digest,
    _prepare,
    _record,
    create_recurrence_in_transaction,
)
from meufinanceiro_persistence.financial_recurrence_suggestion_schema import (
    financial_recurrence_suggestion_decisions,
)


class FinancialRecurrenceSuggestionPersistenceError(
    FinancialRecurrencePersistenceError
):
    """Sanitized persistence failure for recurrence suggestions."""


class FinancialRecurrenceSuggestionNotAvailableError(
    FinancialRecurrenceSuggestionPersistenceError
):
    """The fingerprint is not a suggestion this operator is shown right now.

    Stale, forged, already decided, on an invisible account or in another
    residence: all indistinguishable on purpose.
    """


class FinancialRecurrenceSuggestionNotEditableError(
    FinancialRecurrenceSuggestionPersistenceError
):
    """The suggestion is visible but only the account owner may accept it."""


class FinancialRecurrenceSuggestionConflictError(
    FinancialRecurrenceSuggestionPersistenceError
):
    """A decision incompatible with the one already recorded (fail closed)."""


class FinancialRecurrenceSuggestionLimitError(
    FinancialRecurrenceSuggestionPersistenceError
):
    """A scan or a result at its cap: a list is never silently cut short."""


class FinancialRecurrenceSuggestionStore:
    """Read derived suggestions and record explicit dismiss/accept decisions."""

    def __init__(self, engine: Engine, *, scan_max: int = SUGGESTION_SCAN_MAX) -> None:
        if not isinstance(engine, Engine):
            raise TypeError("engine must be SQLAlchemy Engine")
        if isinstance(scan_max, bool) or not isinstance(scan_max, int) or scan_max < 1:
            raise ValueError("scan_max must be a positive integer")
        self._engine = engine
        self._scan_max = scan_max

    # --- read ------------------------------------------------------------------

    def list_suggestions(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        today: date,
    ) -> tuple[FinancialRecurrenceSuggestion, ...]:
        """The operator's current suggestions. Read-only: nothing is written.

        Visible Movements only (forced RLS), existing equivalent recurrences and the
        decisions that hide a suggestion for this operator already applied. Fails
        explicitly if the scan or the result reaches its cap.
        """
        _require_scope(installation_id, residence_id, operator_id)
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                return self._visible(connection, installation_id, residence_id, today)[
                    0
                ]
        except FinancialMovementAccessError:
            raise FinancialRecurrenceAccessError("recurrence access denied") from None
        except FinancialRecurrencePersistenceError:
            raise
        except DBAPIError:
            raise FinancialRecurrenceSuggestionPersistenceError(
                "recurrence suggestions could not be read"
            ) from None

    # --- dismiss ---------------------------------------------------------------

    def dismiss(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        fingerprint: str,
        today: date,
    ) -> tuple[FinancialRecurrenceSuggestionDecisionRecord, bool]:
        """Personally dismiss a currently shown suggestion: ``(decision, created)``.

        Idempotent: repeating returns the stored decision. A suggestion the operator
        accepted cannot be dismissed (fail closed) and one that is not shown right now
        is "not available". Never touches the ledger or creates a recurrence.
        """
        _require_scope(installation_id, residence_id, operator_id)
        validate_recurrence_suggestion_fingerprint(fingerprint)
        decisions = financial_recurrence_suggestion_decisions
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                own = _own_decision(
                    connection, installation_id, operator_id, fingerprint
                )
                if own is not None:
                    if own.decision is FinancialRecurrenceSuggestionDecision.DISMISSED:
                        return own, False
                    raise FinancialRecurrenceSuggestionConflictError(
                        "recurrence suggestion was already accepted"
                    )
                suggestion = self._candidate(
                    connection, installation_id, residence_id, fingerprint, today
                )
                inserted = (
                    connection.execute(
                        pg_insert(decisions)
                        .values(
                            id=new_financial_resource_id(),
                            installation_id=installation_id,
                            residence_id=residence_id,
                            account_id=suggestion.account_id,
                            operator_id=operator_id,
                            currency=suggestion.currency,
                            fingerprint=fingerprint,
                            decision=FinancialRecurrenceSuggestionDecision.DISMISSED.value,
                            recurrence_id=None,
                            evidence_digest=suggestion.evidence_digest,
                            decided_at=func.transaction_timestamp(),
                        )
                        .on_conflict_do_nothing(
                            index_elements=[
                                decisions.c.installation_id,
                                decisions.c.operator_id,
                                decisions.c.fingerprint,
                            ]
                        )
                        .returning(*decisions.c)
                    )
                    .mappings()
                    .one_or_none()
                )
                if inserted is not None:
                    return _decision_record(inserted), True
                raced = _own_decision(
                    connection, installation_id, operator_id, fingerprint
                )
                if (
                    raced is not None
                    and raced.decision
                    is FinancialRecurrenceSuggestionDecision.DISMISSED
                ):
                    return raced, False
                raise FinancialRecurrenceSuggestionConflictError(
                    "recurrence suggestion decision conflict"
                )
        except FinancialMovementAccessError:
            raise FinancialRecurrenceAccessError("recurrence access denied") from None
        except FinancialRecurrencePersistenceError:
            raise
        except IntegrityError:
            raise FinancialRecurrenceSuggestionConflictError(
                "recurrence suggestion decision conflict"
            ) from None
        except DBAPIError:
            raise FinancialRecurrenceSuggestionPersistenceError(
                "recurrence suggestion could not be dismissed"
            ) from None

    # --- accept ----------------------------------------------------------------

    def accept(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        fingerprint: str,
        idempotency_key: UUID,
        acceptance: FinancialRecurrenceSuggestionAcceptance,
        today: date,
    ) -> tuple[
        FinancialRecurrenceRecord, FinancialRecurrenceSuggestionDecisionRecord, bool
    ]:
        """Create the canonical recurrence and its provenance atomically.

        Returns ``(recurrence, decision, created)``. Order, all in one transaction:
        context and membership, replay of an earlier acceptance, re-run of the
        detector, owner proof, the #254 writer, then the ``ACCEPTED`` decision. Any
        failure rolls back both. The same key with the same material converges even
        after the suggestion has disappeared; anything else already decided is a
        conflict. Writes no occurrence and no Movement.
        """
        _require_scope(installation_id, residence_id, operator_id)
        validate_recurrence_suggestion_fingerprint(fingerprint)
        validate_financial_idempotency_key(idempotency_key)
        if not isinstance(acceptance, FinancialRecurrenceSuggestionAcceptance):
            raise TypeError(
                "acceptance must be FinancialRecurrenceSuggestionAcceptance"
            )
        try:
            with self._engine.begin() as connection:
                _prepare(connection, installation_id, residence_id, operator_id)
                own = _own_decision(
                    connection, installation_id, operator_id, fingerprint
                )
                if own is not None:
                    return self._replay_accept(
                        connection,
                        own,
                        installation_id=installation_id,
                        operator_id=operator_id,
                        idempotency_key=idempotency_key,
                        acceptance=acceptance,
                    )
                suggestion = self._candidate(
                    connection, installation_id, residence_id, fingerprint, today
                )
                if not suggestion.can_accept(operator_id):
                    raise FinancialRecurrenceSuggestionNotEditableError(
                        "only the account owner may accept a recurrence suggestion"
                    )
                recurrence, created = create_recurrence_in_transaction(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    idempotency_key=idempotency_key,
                    draft=acceptance.to_draft(suggestion),
                )
                if not created:
                    # The key already stored this very rule. If the same operator's
                    # accept won a race, converge on it; otherwise fail closed.
                    raced = _own_decision(
                        connection, installation_id, operator_id, fingerprint
                    )
                    if raced is not None and raced.recurrence_id == recurrence.id:
                        return recurrence, raced, False
                    raise FinancialRecurrenceConflictError("recurrence conflict")
                decision = _insert_accepted(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    suggestion=suggestion,
                    recurrence_id=recurrence.id,
                )
                return recurrence, decision, True
        except FinancialMovementAccessError:
            raise FinancialRecurrenceAccessError("recurrence access denied") from None
        except FinancialRecurrencePersistenceError:
            raise
        except IntegrityError:
            # The unique decision (or idempotency key) of a concurrent accept won:
            # this whole transaction, recurrence included, is rolled back.
            raise FinancialRecurrenceSuggestionConflictError(
                "recurrence suggestion decision conflict"
            ) from None
        except DBAPIError:
            raise FinancialRecurrenceSuggestionPersistenceError(
                "recurrence suggestion could not be accepted"
            ) from None

    def _replay_accept(
        self,
        connection: Connection,
        own: FinancialRecurrenceSuggestionDecisionRecord,
        *,
        installation_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        acceptance: FinancialRecurrenceSuggestionAcceptance,
    ) -> tuple[
        FinancialRecurrenceRecord, FinancialRecurrenceSuggestionDecisionRecord, bool
    ]:
        if own.decision is not FinancialRecurrenceSuggestionDecision.ACCEPTED:
            raise FinancialRecurrenceSuggestionConflictError(
                "recurrence suggestion was already dismissed"
            )
        rules = financial_recurrences
        row = (
            connection.execute(
                select(rules).where(
                    rules.c.id == own.recurrence_id,
                    rules.c.installation_id == installation_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or row["idempotency_key"] != idempotency_key:
            raise FinancialRecurrenceSuggestionConflictError(
                "recurrence suggestion was already accepted"
            )
        draft = acceptance.to_draft_for(
            account_id=row["account_id"], currency=row["currency"]
        )
        if row["request_digest"] != _create_digest(operator_id, draft):
            raise FinancialRecurrenceConflictError("recurrence conflict")
        return _record(row), own, False

    # --- detection under RLS ---------------------------------------------------

    def _candidate(
        self,
        connection: Connection,
        installation_id: UUID,
        residence_id: UUID,
        fingerprint: str,
        today: date,
    ) -> FinancialRecurrenceSuggestion:
        suggestions, _hidden = self._visible(
            connection, installation_id, residence_id, today
        )
        for suggestion in suggestions:
            if suggestion.fingerprint == fingerprint:
                return suggestion
        raise FinancialRecurrenceSuggestionNotAvailableError(
            "recurrence suggestion is not available"
        )

    def _visible(
        self,
        connection: Connection,
        installation_id: UUID,
        residence_id: UUID,
        today: date,
    ) -> tuple[tuple[FinancialRecurrenceSuggestion, ...], frozenset[str]]:
        owners, observations = self._scan(
            connection, installation_id, residence_id, today
        )
        suggestions = detect_recurrence_suggestions(
            observations,
            installation_id=installation_id,
            residence_id=residence_id,
            today=today,
            account_owner_by_id=owners,
            existing_rules=_existing_rules(connection, installation_id, residence_id),
        )
        hidden = _hidden_fingerprints(
            connection, installation_id, [s.fingerprint for s in suggestions]
        )
        shown = tuple(s for s in suggestions if s.fingerprint not in hidden)
        if len(shown) > SUGGESTION_LIST_MAX:
            raise FinancialRecurrenceSuggestionLimitError(
                "recurrence suggestion limit reached"
            )
        return shown, hidden

    def _bounded_ids(self, connection: Connection, statement: Select[Any]) -> set[UUID]:
        """One set of ids, read with an explicit cap (never silently cut short)."""
        ids = set(connection.scalars(statement.limit(self._scan_max + 1)).all())
        if len(ids) > self._scan_max:
            raise FinancialRecurrenceSuggestionLimitError(
                "recurrence suggestion scan limit reached"
            )
        return ids

    def _scan(
        self,
        connection: Connection,
        installation_id: UUID,
        residence_id: UUID,
        today: date,
    ) -> tuple[dict[UUID, UUID], list[FinancialRecurrenceObservation]]:
        first, last = recurrence_suggestion_window(today)
        movements = financial_movements
        accounts = financial_accounts
        # Two set reads instead of per-row anti-joins: a correlated NOT EXISTS lets
        # the planner pick a nested loop over the whole residence when it has no
        # statistics yet (right after a large import), which is quadratic. These
        # are linear scans on unique indexes and the exclusion is done once below.
        reversed_ids = self._bounded_ids(
            connection,
            select(movements.c.reversal_of_id).where(
                movements.c.installation_id == installation_id,
                movements.c.residence_id == residence_id,
                movements.c.reversal_of_id.is_not(None),
            ),
        )
        linked_ids = self._bounded_ids(
            connection,
            select(financial_recurrence_occurrences.c.movement_id).where(
                financial_recurrence_occurrences.c.installation_id == installation_id,
                financial_recurrence_occurrences.c.residence_id == residence_id,
                financial_recurrence_occurrences.c.movement_id.is_not(None),
            ),
        )
        statement = (
            select(
                movements.c.id,
                movements.c.account_id,
                movements.c.currency,
                movements.c.amount,
                movements.c.description,
                movements.c.effective_date,
                accounts.c.owner_operator_id,
            )
            .select_from(
                movements.join(
                    accounts,
                    (accounts.c.id == movements.c.account_id)
                    & (accounts.c.installation_id == movements.c.installation_id)
                    & (accounts.c.residence_id == movements.c.residence_id),
                )
            )
            .where(
                movements.c.installation_id == installation_id,
                movements.c.residence_id == residence_id,
                movements.c.role == FinancialMovementRole.STANDARD.value,
                movements.c.result_effect == FinancialResultEffect.EXPENSE.value,
                movements.c.effective_date >= first,
                movements.c.effective_date <= last,
                movements.c.description.is_not(None),
                accounts.c.status == "ACTIVE",
            )
            .order_by(movements.c.effective_date, movements.c.id)
            .limit(self._scan_max + 1)
        )
        rows = connection.execute(statement).mappings().all()
        if len(rows) > self._scan_max:
            raise FinancialRecurrenceSuggestionLimitError(
                "recurrence suggestion scan limit reached"
            )
        excluded = reversed_ids | linked_ids
        rows = [row for row in rows if row["id"] not in excluded]
        owners: dict[UUID, UUID] = {}
        observations: list[FinancialRecurrenceObservation] = []
        try:
            for row in rows:
                owners[row["account_id"]] = row["owner_operator_id"]
                observations.append(
                    FinancialRecurrenceObservation(
                        movement_id=row["id"],
                        account_id=row["account_id"],
                        currency=row["currency"],
                        description=row["description"],
                        effective_date=row["effective_date"],
                        amount=-row["amount"],
                    )
                )
        except (KeyError, TypeError, ValueError):
            raise FinancialRecurrenceSuggestionPersistenceError(
                "recurrence suggestion state is invalid"
            ) from None
        return owners, observations


# --- helpers ---------------------------------------------------------------------


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


def _existing_rules(
    connection: Connection, installation_id: UUID, residence_id: UUID
) -> list[FinancialRecurrenceRuleKey]:
    rules = financial_recurrences
    rows = (
        connection.execute(
            select(
                rules.c.account_id,
                rules.c.currency,
                rules.c.result_effect,
                rules.c.description,
            )
            .where(
                rules.c.installation_id == installation_id,
                rules.c.residence_id == residence_id,
            )
            .limit(RECURRENCE_LIST_MAX + 1)
        )
        .mappings()
        .all()
    )
    if len(rows) > RECURRENCE_LIST_MAX:
        raise FinancialRecurrenceSuggestionLimitError("recurrence limit reached")
    return [
        FinancialRecurrenceRuleKey(
            account_id=row["account_id"],
            currency=row["currency"],
            result_effect=FinancialResultEffect(row["result_effect"]),
            description=row["description"],
        )
        for row in rows
    ]


def _hidden_fingerprints(
    connection: Connection, installation_id: UUID, fingerprints: list[str]
) -> frozenset[str]:
    """Fingerprints hidden for this operator: its own dismissals, anyone's accept.

    The row policy already limits what is readable (DISMISSED only to its author,
    ACCEPTED to the account audience), so one bounded query answers both.
    """
    if not fingerprints:
        return frozenset()
    decisions = financial_recurrence_suggestion_decisions
    return frozenset(
        connection.scalars(
            select(decisions.c.fingerprint).where(
                decisions.c.installation_id == installation_id,
                decisions.c.fingerprint.in_(fingerprints),
            )
        ).all()
    )


def _own_decision(
    connection: Connection,
    installation_id: UUID,
    operator_id: UUID,
    fingerprint: str,
) -> FinancialRecurrenceSuggestionDecisionRecord | None:
    decisions = financial_recurrence_suggestion_decisions
    row = (
        connection.execute(
            select(decisions).where(
                decisions.c.installation_id == installation_id,
                decisions.c.operator_id == operator_id,
                decisions.c.fingerprint == fingerprint,
            )
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else _decision_record(row)


def _insert_accepted(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
    suggestion: FinancialRecurrenceSuggestion,
    recurrence_id: UUID,
) -> FinancialRecurrenceSuggestionDecisionRecord:
    decisions = financial_recurrence_suggestion_decisions
    row = (
        connection.execute(
            pg_insert(decisions)
            .values(
                id=new_financial_resource_id(),
                installation_id=installation_id,
                residence_id=residence_id,
                account_id=suggestion.account_id,
                operator_id=operator_id,
                currency=suggestion.currency,
                fingerprint=suggestion.fingerprint,
                decision=FinancialRecurrenceSuggestionDecision.ACCEPTED.value,
                recurrence_id=recurrence_id,
                evidence_digest=suggestion.evidence_digest,
                decided_at=func.transaction_timestamp(),
            )
            .returning(*decisions.c)
        )
        .mappings()
        .one()
    )
    return _decision_record(row)


def _decision_record(
    row: RowMapping,
) -> FinancialRecurrenceSuggestionDecisionRecord:
    try:
        return FinancialRecurrenceSuggestionDecisionRecord(
            id=row["id"],
            account_id=row["account_id"],
            operator_id=row["operator_id"],
            currency=row["currency"],
            fingerprint=row["fingerprint"],
            decision=FinancialRecurrenceSuggestionDecision(row["decision"]),
            recurrence_id=row["recurrence_id"],
            evidence_digest=row["evidence_digest"],
            decided_at=row["decided_at"],
        )
    except (KeyError, TypeError, ValueError):
        raise FinancialRecurrenceSuggestionPersistenceError(
            "recurrence suggestion decision state is invalid"
        ) from None


__all__ = [
    "FinancialRecurrenceSuggestionConflictError",
    "FinancialRecurrenceSuggestionLimitError",
    "FinancialRecurrenceSuggestionNotAvailableError",
    "FinancialRecurrenceSuggestionNotEditableError",
    "FinancialRecurrenceSuggestionPersistenceError",
    "FinancialRecurrenceSuggestionStore",
]
