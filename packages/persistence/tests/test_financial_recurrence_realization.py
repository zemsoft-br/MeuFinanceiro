"""PostgreSQL-backed proofs for the explicit, atomic realization of an occurrence.

Registering is the only act that produces a financial fact, and it produces exactly
one canonical STANDARD Movement, linked in the same transaction. Everything runs
through the non-superuser runtime role with forced RLS.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    FinancialMovementDraft,
    FinancialMovementReversalDraft,
    FinancialMovementRole,
    FinancialOccurrenceMovementState,
    FinancialOccurrenceStatus,
    FinancialRecurrenceDraft,
    FinancialRecurrenceOccurrenceRecord,
    FinancialRecurrenceRealizationDraft,
    FinancialRecurrenceRecord,
    FinancialRecurrenceReplacement,
    FinancialRecurrenceStatus,
    FinancialRecurrenceWindow,
    FinancialResultEffect,
    Money,
    new_financial_idempotency_key,
)
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

import meufinanceiro_persistence.financial_recurrence_store as store_module
from meufinanceiro_persistence.financial_audit_schema import financial_audit_events
from meufinanceiro_persistence.financial_movement_allocation_schema import (
    financial_movement_allocation_sets,
)
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementStore,
    _set_context,
)
from meufinanceiro_persistence.financial_recurrence_schema import (
    financial_recurrence_occurrences,
)
from meufinanceiro_persistence.financial_recurrence_store import (
    FinancialRecurrenceAccountNotFoundError,
    FinancialRecurrenceConflictError,
    FinancialRecurrenceInvalidShapeError,
    FinancialRecurrenceNotEditableError,
    FinancialRecurrenceOccurrenceNotFoundError,
    FinancialRecurrenceOccurrenceStateError,
    FinancialRecurrencePersistenceError,
    FinancialRecurrenceStore,
)

if TYPE_CHECKING:
    from conftest import BudgetWorld

_TODAY = date(2026, 10, 6)
_OCT = date(2026, 10, 1)
_NOV = date(2026, 11, 1)
_DEC = date(2026, 12, 1)


def _store(world: BudgetWorld) -> FinancialRecurrenceStore:
    return FinancialRecurrenceStore(world.runtime)


def _rule(
    world: BudgetWorld, account_id: UUID | None = None, **overrides: Any
) -> FinancialRecurrenceRecord:
    values: dict[str, Any] = {
        "account_id": account_id or world.account(),
        "description": "Internet",
        "result_effect": FinancialResultEffect.EXPENSE,
        "expected": Money(Decimal("120"), "BRL"),
        "start_date": date(2026, 1, 10),
        "day_of_month": 10,
        "end_date": None,
    }
    values.update(overrides)
    return _store(world).create_recurrence(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialRecurrenceDraft(**values),
    )


def _pending(
    world: BudgetWorld,
    rule: FinancialRecurrenceRecord,
    period: date = _OCT,
) -> FinancialRecurrenceOccurrenceRecord:
    result = _store(world).generate_occurrences(
        **world.scope(),
        recurrence_id=rule.id,
        window=FinancialRecurrenceWindow(period, period),
    )
    (occurrence,) = result.occurrences
    return occurrence


def _draft(
    amount: str = "127.50",
    effective: date = date(2026, 10, 11),
    competence: date = date(2026, 10, 1),
    currency: str = "BRL",
) -> FinancialRecurrenceRealizationDraft:
    return FinancialRecurrenceRealizationDraft(
        actual=Money(Decimal(amount), currency),
        effective_date=effective,
        competence_date=competence,
    )


def _realize(
    world: BudgetWorld,
    occurrence: FinancialRecurrenceOccurrenceRecord,
    *,
    key: UUID | None = None,
    draft: FinancialRecurrenceRealizationDraft | None = None,
    operator_id: UUID | None = None,
) -> FinancialRecurrenceOccurrenceRecord:
    return _store(world).realize_occurrence(
        **world.scope(operator_id),
        occurrence_id=occurrence.id,
        idempotency_key=key or new_financial_idempotency_key(),
        draft=draft or _draft(),
    )


def _count(world: BudgetWorld, table: Any, *where: Any) -> int:
    with world.engine.begin() as connection:
        value = connection.scalar(select(func.count()).select_from(table).where(*where))
    assert isinstance(value, int)
    return value


def _movements(world: BudgetWorld) -> list[Any]:
    with world.engine.begin() as connection:
        return list(connection.execute(select(financial_movements)).mappings().all())


def _status(world: BudgetWorld, occurrence_id: UUID) -> str:
    with world.engine.begin() as connection:
        value = connection.scalar(
            select(financial_recurrence_occurrences.c.status).where(
                financial_recurrence_occurrences.c.id == occurrence_id
            )
        )
    assert isinstance(value, str)
    return value


def _get(
    world: BudgetWorld, occurrence: FinancialRecurrenceOccurrenceRecord
) -> FinancialRecurrenceOccurrenceRecord:
    return _store(world).get_occurrence(**world.scope(), occurrence_id=occurrence.id)


# --- the happy path ------------------------------------------------------------


def test_realize_creates_exactly_one_standard_movement_and_links_it(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world)
    occurrence = _pending(budget_world, rule)
    assert _movements(budget_world) == []  # zero Movement before Registrar

    realized = _realize(budget_world, occurrence)

    assert realized.status is FinancialOccurrenceStatus.REALIZED
    link = realized.realization
    assert link is not None
    (movement,) = _movements(budget_world)
    assert movement["id"] == link.movement_id
    assert movement["role"] == FinancialMovementRole.STANDARD.value
    assert movement["result_effect"] == "EXPENSE"
    assert movement["amount"] == Decimal("-127.50")  # signed by the canonical writer
    assert movement["currency"] == "BRL"
    assert movement["account_id"] == rule.account_id
    assert movement["effective_date"] == date(2026, 10, 11)
    assert movement["competence_date"] == date(2026, 10, 1)
    assert movement["description"] == "Internet"
    assert movement["created_by_operator_id"] == budget_world.owner_id
    assert movement["reversal_of_id"] is None
    # Expected stays the plan; actual is the fact. They may differ.
    assert realized.expected.amount == Decimal("120")
    assert link.actual == Money(Decimal("127.50"), "BRL")
    assert link.effective_date == date(2026, 10, 11)
    assert link.competence_date == date(2026, 10, 1)
    assert link.movement_state is FinancialOccurrenceMovementState.ACTIVE
    assert _get(budget_world, occurrence) == realized
    # The canonical writer's audit event is written exactly once.
    assert (
        _count(
            budget_world,
            financial_audit_events,
            financial_audit_events.c.subject_id == movement["id"],
        )
        == 1
    )
    # Realizing never classifies.
    assert _count(budget_world, financial_movement_allocation_sets) == 0


def test_an_income_occurrence_creates_a_positive_income_movement(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world, result_effect=FinancialResultEffect.INCOME)
    occurrence = _pending(budget_world, rule)
    _realize(budget_world, occurrence, draft=_draft("3000"))
    (movement,) = _movements(budget_world)
    assert movement["amount"] == Decimal("3000")
    assert movement["result_effect"] == "INCOME"


def test_actual_may_equal_or_differ_from_expected_without_touching_the_rule(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world)
    same = _realize(
        budget_world, _pending(budget_world, rule, _OCT), draft=_draft("120")
    )
    other = _realize(
        budget_world,
        _pending(budget_world, rule, _NOV),
        draft=_draft("99.99", date(2026, 11, 9), date(2026, 11, 1)),
    )
    assert same.realization is not None and other.realization is not None
    assert same.realization.actual.amount == Decimal("120")
    assert other.realization.actual.amount == Decimal("99.99")
    assert other.expected.amount == Decimal("120")
    current = _store(budget_world).get_recurrence(
        **budget_world.scope(), recurrence_id=rule.id
    )
    assert current == rule  # the rule is untouched
    assert len(_movements(budget_world)) == 2


def test_a_paused_rule_does_not_block_registering_an_existing_pending(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world)
    occurrence = _pending(budget_world, rule)
    paused = _store(budget_world).pause_recurrence(
        **budget_world.scope(), recurrence_id=rule.id
    )
    assert paused.status is FinancialRecurrenceStatus.PAUSED
    assert (
        _realize(budget_world, occurrence).status is FinancialOccurrenceStatus.REALIZED
    )


# --- idempotency ---------------------------------------------------------------


def test_an_identical_retry_converges_on_the_same_movement(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world)
    occurrence = _pending(budget_world, rule)
    key = new_financial_idempotency_key()

    first = _realize(budget_world, occurrence, key=key)
    again = _realize(budget_world, occurrence, key=key)

    assert again == first
    assert len(_movements(budget_world)) == 1


def test_an_incompatible_retry_fails_closed_and_writes_nothing(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world)
    occurrence = _pending(budget_world, rule)
    other = _pending(budget_world, rule, _NOV)
    key = new_financial_idempotency_key()
    first = _realize(budget_world, occurrence, key=key)

    # Same key, other amount or other date.
    with pytest.raises(FinancialRecurrenceConflictError):
        _realize(budget_world, occurrence, key=key, draft=_draft("128"))
    with pytest.raises(FinancialRecurrenceConflictError):
        _realize(
            budget_world,
            occurrence,
            key=key,
            draft=_draft(effective=date(2026, 10, 12)),
        )
    # Same key aimed at another occurrence.
    with pytest.raises(FinancialRecurrenceConflictError):
        _realize(budget_world, other, key=key)
    # Another key on the already realized occurrence.
    with pytest.raises(FinancialRecurrenceOccurrenceStateError):
        _realize(budget_world, occurrence)

    assert len(_movements(budget_world)) == 1
    assert _get(budget_world, occurrence) == first
    assert _status(budget_world, other.id) == "PENDING"


def test_a_retry_after_a_movement_reversal_still_converges_without_a_new_movement(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world)
    occurrence = _pending(budget_world, rule)
    key = new_financial_idempotency_key()
    first = _realize(budget_world, occurrence, key=key)
    assert first.realization is not None
    FinancialMovementStore(budget_world.runtime).reverse_movement(
        **budget_world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementReversalDraft(
            movement_id=first.realization.movement_id,
            effective_date=date(2026, 10, 12),
            competence_date=date(2026, 10, 1),
            reason="Cobrança duplicada",
        ),
    )

    again = _realize(budget_world, occurrence, key=key)

    assert again.realization is not None
    assert again.realization.movement_id == first.realization.movement_id
    assert len(_movements(budget_world)) == 2  # the Movement and its reversal only


# --- reversal does not reopen ---------------------------------------------------


def test_a_reversal_never_reopens_the_occurrence(budget_world: BudgetWorld) -> None:
    rule = _rule(budget_world)
    occurrence = _pending(budget_world, rule)
    realized = _realize(budget_world, occurrence)
    assert realized.realization is not None

    FinancialMovementStore(budget_world.runtime).reverse_movement(
        **budget_world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementReversalDraft(
            movement_id=realized.realization.movement_id,
            effective_date=date(2026, 10, 12),
            competence_date=date(2026, 10, 1),
            reason="Cobrança duplicada",
        ),
    )

    after = _get(budget_world, occurrence)
    assert after.status is FinancialOccurrenceStatus.REALIZED
    assert after.realization is not None
    assert after.realization.movement_id == realized.realization.movement_id
    assert after.realization.movement_state is FinancialOccurrenceMovementState.REVERSED
    assert after.realization.actual == realized.realization.actual
    # It stays terminal: neither a new Movement, a skip nor a regeneration.
    with pytest.raises(FinancialRecurrenceOccurrenceStateError):
        _realize(budget_world, occurrence)
    with pytest.raises(FinancialRecurrenceOccurrenceStateError):
        _store(budget_world).skip_occurrence(
            **budget_world.scope(), occurrence_id=occurrence.id
        )
    regenerated = _store(budget_world).generate_occurrences(
        **budget_world.scope(),
        recurrence_id=rule.id,
        window=FinancialRecurrenceWindow(_OCT, _OCT),
    )
    assert regenerated.created_count == 0
    assert len(_movements(budget_world)) == 2


# --- terminal states and revalidation --------------------------------------------


def test_skipped_and_superseded_occurrences_cannot_be_realized(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world)
    skipped = _pending(budget_world, rule, _NOV)
    _store(budget_world).skip_occurrence(
        **budget_world.scope(), occurrence_id=skipped.id
    )
    superseded = _pending(budget_world, rule, _DEC)
    _store(budget_world).replace_recurrence(
        **budget_world.scope(),
        recurrence_id=rule.id,
        replacement=FinancialRecurrenceReplacement(
            expected_version=1,
            description="Internet",
            expected_amount=Decimal("130"),
            day_of_month=10,
            end_date=None,
        ),
        today=_TODAY,
    )
    for occurrence in (skipped, superseded):
        with pytest.raises(FinancialRecurrenceOccurrenceStateError):
            _realize(budget_world, occurrence)
    assert _movements(budget_world) == []


def test_an_inactive_account_fails_closed_without_any_state(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    rule = _rule(budget_world, account)
    occurrence = _pending(budget_world, rule)
    budget_world.archive_account(account)

    with pytest.raises(FinancialRecurrenceAccountNotFoundError):
        _realize(budget_world, occurrence)

    assert _movements(budget_world) == []
    assert _status(budget_world, occurrence.id) == "PENDING"


def test_a_foreign_currency_actual_is_rejected_without_state(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world)
    occurrence = _pending(budget_world, rule)
    with pytest.raises(FinancialRecurrenceInvalidShapeError):
        _realize(budget_world, occurrence, draft=_draft(currency="USD"))
    assert _movements(budget_world) == []
    assert _status(budget_world, occurrence.id) == "PENDING"


def test_only_the_owner_registers_and_hidden_occurrences_are_not_found(
    budget_world: BudgetWorld,
) -> None:
    household = _pending(budget_world, _rule(budget_world))
    private = _pending(
        budget_world, _rule(budget_world, budget_world.account(household=False))
    )
    member = budget_world.member_id

    with pytest.raises(FinancialRecurrenceNotEditableError):
        _realize(budget_world, household, operator_id=member)
    with pytest.raises(FinancialRecurrenceOccurrenceNotFoundError):
        _realize(budget_world, private, operator_id=member)
    with pytest.raises(FinancialRecurrenceOccurrenceNotFoundError):
        _store(budget_world).realize_occurrence(
            **budget_world.scope(
                budget_world.outsider_id, residence_id=budget_world.other_residence_id
            ),
            occurrence_id=household.id,
            idempotency_key=new_financial_idempotency_key(),
            draft=_draft(),
        )
    assert _movements(budget_world) == []


# --- atomicity ------------------------------------------------------------------


def test_a_failure_after_the_movement_leaves_neither_movement_nor_link(
    budget_world: BudgetWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    rule = _rule(budget_world)
    occurrence = _pending(budget_world, rule)
    movement_audits = _count(budget_world, financial_audit_events)

    def explode(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("synthetic failure between the Movement and the link")

    monkeypatch.setattr(store_module, "_link_occurrence_to_movement", explode)

    with pytest.raises(RuntimeError):
        _realize(budget_world, occurrence)

    assert _movements(budget_world) == []  # the Movement rolled back
    assert _count(budget_world, financial_audit_events) == movement_audits
    assert _status(budget_world, occurrence.id) == "PENDING"
    monkeypatch.undo()
    # The very same command now succeeds once, from a clean state.
    assert (
        _realize(budget_world, occurrence).status is FinancialOccurrenceStatus.REALIZED
    )
    assert len(_movements(budget_world)) == 1


def test_a_database_rejection_of_the_link_rolls_the_movement_back(
    budget_world: BudgetWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    rule = _rule(budget_world)
    occurrence = _pending(budget_world, rule)
    original = store_module._link_occurrence_to_movement

    def link_to_a_missing_movement(connection: Any, **kwargs: Any) -> Any:
        return original(connection, **{**kwargs, "movement_id": uuid4()})

    monkeypatch.setattr(
        store_module, "_link_occurrence_to_movement", link_to_a_missing_movement
    )
    with pytest.raises(FinancialRecurrencePersistenceError):
        _realize(budget_world, occurrence)
    assert _movements(budget_world) == []
    assert _status(budget_world, occurrence.id) == "PENDING"


def test_an_unexpected_writer_refusal_stays_sanitized_and_leaves_no_state(
    budget_world: BudgetWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    from meufinanceiro_persistence.financial_movement_store import (
        FinancialMovementIdempotencyConflictError,
    )

    rule = _rule(budget_world)
    occurrence = _pending(budget_world, rule)

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise FinancialMovementIdempotencyConflictError("synthetic refusal")

    monkeypatch.setattr(store_module, "create_standard_movement_in_transaction", refuse)
    with pytest.raises(FinancialRecurrencePersistenceError) as raised:
        _realize(budget_world, occurrence)
    assert "synthetic" not in str(raised.value)
    assert _movements(budget_world) == []
    assert _status(budget_world, occurrence.id) == "PENDING"


def test_the_database_refuses_a_link_to_a_movement_from_another_transaction(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world)
    occurrence = _pending(budget_world, rule)
    # A Movement that already exists (earlier transaction), same account and effect.
    movement = FinancialMovementStore(budget_world.runtime).create_movement(
        **budget_world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementDraft(
            account_id=rule.account_id,
            amount=Money(Decimal("-120"), "BRL"),
            result_effect=FinancialResultEffect.EXPENSE,
            effective_date=date(2026, 10, 10),
            competence_date=date(2026, 10, 1),
            description="Avulso",
        ),
    )
    with pytest.raises(DBAPIError):
        with budget_world.runtime.begin() as connection:
            _set_context(connection, **budget_world.scope())
            connection.execute(
                update(financial_recurrence_occurrences)
                .where(financial_recurrence_occurrences.c.id == occurrence.id)
                .values(
                    status="REALIZED",
                    movement_id=movement.id,
                    realization_idempotency_key=new_financial_idempotency_key(),
                    realization_request_digest="a" * 64,
                    realized_at=func.transaction_timestamp(),
                    realized_by_operator_id=budget_world.owner_id,
                    updated_at=func.transaction_timestamp(),
                )
            )
    assert _status(budget_world, occurrence.id) == "PENDING"


def test_a_realized_occurrence_cannot_be_rewritten_at_the_database(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world)
    occurrence = _pending(budget_world, rule)
    realized = _realize(budget_world, occurrence)
    for values in (
        {"status": "SKIPPED", "skipped_at": func.transaction_timestamp()},
        {"status": "PENDING"},
        {"movement_id": uuid4()},
    ):
        with pytest.raises(DBAPIError):
            with budget_world.runtime.begin() as connection:
                _set_context(connection, **budget_world.scope())
                connection.execute(
                    update(financial_recurrence_occurrences)
                    .where(financial_recurrence_occurrences.c.id == occurrence.id)
                    .values(**values)
                )
    assert _get(budget_world, occurrence) == realized
    # And nothing can delete the link or the Movement behind it.
    with pytest.raises(DBAPIError):
        with budget_world.runtime.begin() as connection:
            _set_context(connection, **budget_world.scope())
            connection.execute(text("DELETE FROM finance.movements"))


# --- concurrency ----------------------------------------------------------------


def test_concurrent_identical_realizations_create_one_movement(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world)
    occurrence = _pending(budget_world, rule)
    key = new_financial_idempotency_key()
    barrier = Barrier(6)

    def attempt() -> UUID:
        barrier.wait()
        realized = _realize(budget_world, occurrence, key=key)
        assert realized.realization is not None
        return realized.realization.movement_id

    with ThreadPoolExecutor(max_workers=6) as pool:
        ids = {f.result() for f in [pool.submit(attempt) for _ in range(6)]}

    assert len(ids) == 1
    assert len(_movements(budget_world)) == 1


def test_concurrent_realizations_with_different_keys_have_one_winner(
    budget_world: BudgetWorld,
) -> None:
    rule = _rule(budget_world)
    occurrence = _pending(budget_world, rule)
    barrier = Barrier(6)

    def attempt() -> str:
        barrier.wait()
        try:
            _realize(budget_world, occurrence)
        except FinancialRecurrenceOccurrenceStateError:
            return "closed"
        return "won"

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = [f.result() for f in [pool.submit(attempt) for _ in range(6)]]

    assert results.count("won") == 1 and results.count("closed") == 5
    assert len(_movements(budget_world)) == 1


def test_realize_racing_skip_leaves_a_consistent_outcome(
    budget_world: BudgetWorld,
) -> None:
    for _ in range(4):
        rule = _rule(budget_world)
        occurrence = _pending(budget_world, rule)
        barrier = Barrier(2)

        def do_realize(
            occ: FinancialRecurrenceOccurrenceRecord = occurrence,
            gate: Barrier = barrier,
        ) -> str:
            gate.wait()
            try:
                _realize(budget_world, occ)
            except FinancialRecurrenceOccurrenceStateError:
                return "realize-closed"
            return "realized"

        def do_skip(
            occ: FinancialRecurrenceOccurrenceRecord = occurrence,
            gate: Barrier = barrier,
        ) -> str:
            gate.wait()
            try:
                _store(budget_world).skip_occurrence(
                    **budget_world.scope(), occurrence_id=occ.id
                )
            except FinancialRecurrenceOccurrenceStateError:
                return "skip-closed"
            return "skipped"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = {
                f.result() for f in [pool.submit(do_realize), pool.submit(do_skip)]
            }

        status = _status(budget_world, occurrence.id)
        linked = _count(
            budget_world,
            financial_recurrence_occurrences,
            financial_recurrence_occurrences.c.id == occurrence.id,
            financial_recurrence_occurrences.c.movement_id.is_not(None),
        )
        assert outcomes in (
            {"realized", "skip-closed"},
            {"realize-closed", "skipped"},
        )
        assert (status, linked) in (("REALIZED", 1), ("SKIPPED", 0))
    # Exactly the realized ones produced a Movement.
    realized = _count(
        budget_world,
        financial_recurrence_occurrences,
        financial_recurrence_occurrences.c.status == "REALIZED",
    )
    assert len(_movements(budget_world)) == realized


def test_realize_racing_an_edit_never_rewrites_a_realized_occurrence(
    budget_world: BudgetWorld,
) -> None:
    for round_index in range(3):
        rule = _rule(budget_world)
        occurrence = _pending(budget_world, rule, _DEC)
        barrier = Barrier(2)

        def do_realize(
            occ: FinancialRecurrenceOccurrenceRecord = occurrence,
            gate: Barrier = barrier,
        ) -> None:
            gate.wait()
            try:
                _realize(budget_world, occ)
            except FinancialRecurrenceOccurrenceStateError:
                pass

        def do_edit(
            rec: FinancialRecurrenceRecord = rule, gate: Barrier = barrier
        ) -> None:
            gate.wait()
            _store(budget_world).replace_recurrence(
                **budget_world.scope(),
                recurrence_id=rec.id,
                replacement=FinancialRecurrenceReplacement(
                    expected_version=1,
                    description="Internet",
                    expected_amount=Decimal("150") + round_index,
                    day_of_month=10,
                    end_date=None,
                ),
                today=_TODAY,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            for future in [pool.submit(do_realize), pool.submit(do_edit)]:
                future.result()

        status = _status(budget_world, occurrence.id)
        linked = _count(
            budget_world,
            financial_recurrence_occurrences,
            financial_recurrence_occurrences.c.id == occurrence.id,
            financial_recurrence_occurrences.c.movement_id.is_not(None),
        )
        assert (status, linked) in (("REALIZED", 1), ("SUPERSEDED", 0))
    realized = _count(
        budget_world,
        financial_recurrence_occurrences,
        financial_recurrence_occurrences.c.status == "REALIZED",
    )
    assert len(_movements(budget_world)) == realized
