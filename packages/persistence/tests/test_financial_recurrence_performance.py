"""Shape and cost proofs for recurrences on a household with many rules.

The claim is about *shape*, not a stopwatch: every call runs a fixed number of SQL
statements regardless of how many rules, months or occurrences exist, nothing is
repeated per rule or per occurrence, and the window queries are served by the
indexes that were created for them. Time is only a generous ceiling.
"""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from meufinanceiro_finance import (
    FinancialRecurrenceDraft,
    FinancialRecurrenceRealizationDraft,
    FinancialRecurrenceRecord,
    FinancialRecurrenceWindow,
    FinancialResultEffect,
    Money,
    new_financial_idempotency_key,
)
from sqlalchemy import event, text

from meufinanceiro_persistence.financial_movement_store import _set_context
from meufinanceiro_persistence.financial_recurrence_store import (
    FinancialRecurrenceStore,
)

if TYPE_CHECKING:
    from conftest import BudgetWorld

_OCT = date(2026, 10, 1)


def _store(world: BudgetWorld) -> FinancialRecurrenceStore:
    return FinancialRecurrenceStore(world.runtime)


def _rule(
    world: BudgetWorld, account_id: UUID, description: str = "Internet"
) -> FinancialRecurrenceRecord:
    return _store(world).create_recurrence(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialRecurrenceDraft(
            account_id=account_id,
            description=description,
            result_effect=FinancialResultEffect.EXPENSE,
            expected=Money(Decimal("120"), "BRL"),
            start_date=date(2026, 1, 10),
            day_of_month=10,
        ),
    )


class _Counter:
    """Counts the statements one call sends, excluding transaction control."""

    def __init__(self, world: BudgetWorld) -> None:
        self._engine = world.runtime
        self.count = 0

    def _on(self, *_: Any) -> None:
        self.count += 1

    def __enter__(self) -> _Counter:
        event.listen(self._engine, "before_cursor_execute", self._on)
        return self

    def __exit__(self, *_: object) -> None:
        event.remove(self._engine, "before_cursor_execute", self._on)


def _statements(world: BudgetWorld, call: Any) -> int:
    with _Counter(world) as counter:
        call()
    return counter.count


def test_statement_count_is_fixed_whatever_the_number_of_rules(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    first = _rule(budget_world, account)
    window = FinancialRecurrenceWindow(_OCT, date(2026, 12, 1))
    scope = budget_world.scope()
    store = _store(budget_world)
    store.generate_occurrences(**scope, recurrence_id=first.id, window=window)

    def read_everything() -> None:
        store.list_recurrences(**scope)
        store.list_occurrences(**scope, window=window)

    small = _statements(budget_world, read_everything)
    for index in range(60):
        rule = _rule(budget_world, account, f"Regra {index}")
        store.generate_occurrences(**scope, recurrence_id=rule.id, window=window)
    large = _statements(budget_world, read_everything)

    assert small == large
    assert large <= 10  # contexts, memberships, rules, one window: no per-row query


def test_generation_costs_the_same_for_one_month_and_for_twelve(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    scope = budget_world.scope()
    store = _store(budget_world)
    one = _rule(budget_world, account, "Um mês")
    twelve = _rule(budget_world, account, "Doze meses")
    single = _statements(
        budget_world,
        lambda: store.generate_occurrences(
            **scope,
            recurrence_id=one.id,
            window=FinancialRecurrenceWindow(_OCT, _OCT),
        ),
    )
    year = _statements(
        budget_world,
        lambda: store.generate_occurrences(
            **scope,
            recurrence_id=twelve.id,
            window=FinancialRecurrenceWindow(_OCT, date(2027, 9, 1)),
        ),
    )
    assert single == year  # one insert for the whole window, not one per month
    replay = _statements(
        budget_world,
        lambda: store.generate_occurrences(
            **scope,
            recurrence_id=twelve.id,
            window=FinancialRecurrenceWindow(_OCT, date(2027, 9, 1)),
        ),
    )
    assert replay == year


def test_reading_realized_occurrences_adds_a_fixed_number_of_statements(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    scope = budget_world.scope()
    store = _store(budget_world)
    rule = _rule(budget_world, account)
    window = FinancialRecurrenceWindow(_OCT, date(2027, 9, 1))
    created = store.generate_occurrences(**scope, recurrence_id=rule.id, window=window)
    before = _statements(
        budget_world, lambda: store.list_occurrences(**scope, window=window)
    )
    for occurrence in created.occurrences[:6]:
        store.realize_occurrence(
            **scope,
            occurrence_id=occurrence.id,
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialRecurrenceRealizationDraft(
                actual=Money(Decimal("121"), "BRL"),
                effective_date=occurrence.scheduled_date,
                competence_date=occurrence.period_start,
            ),
        )
    after = _statements(
        budget_world, lambda: store.list_occurrences(**scope, window=window)
    )
    # Two extra statements for the whole page (the Movements and their reversals),
    # never one per realized occurrence.
    assert after - before == 2


def test_a_large_household_stays_within_a_generous_ceiling_and_uses_indexes(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    scope = budget_world.scope()
    store = _store(budget_world)
    window = FinancialRecurrenceWindow(_OCT, date(2027, 9, 1))
    for index in range(200):
        rule = _rule(budget_world, account, f"Regra {index}")
        store.generate_occurrences(**scope, recurrence_id=rule.id, window=window)

    with budget_world.engine.begin() as connection:
        connection.execute(text("ANALYZE finance.recurrence_occurrences"))
        connection.execute(text("ANALYZE finance.recurrences"))

    started = time.perf_counter()
    items = store.list_occurrences(**scope, window=window)
    rules = store.list_recurrences(**scope)
    elapsed = time.perf_counter() - started
    assert len(items) == 200 * 12 and len(rules) == 200
    assert elapsed < 5.0  # a ceiling against a runaway plan, not a benchmark

    # The window query is served by the period index, and the pending index exists
    # for the supersede step of an edit.
    with budget_world.runtime.begin() as connection:
        _set_context(connection, **scope)
        # Statistics now describe a 2400-row table; asking for a single month, the
        # planner must have an index to serve it (not only a table scan).
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            row[0]
            for row in connection.execute(
                text(
                    "EXPLAIN SELECT * FROM finance.recurrence_occurrences "
                    "WHERE installation_id = :i AND residence_id = :r "
                    "AND period_start >= :a AND period_start <= :b "
                    "AND status <> 'SUPERSEDED'"
                ),
                {
                    "i": budget_world.installation_id,
                    "r": budget_world.residence_id,
                    "a": _OCT,
                    "b": _OCT,
                },
            )
        )
        pending_plan = "\n".join(
            row[0]
            for row in connection.execute(
                text(
                    "EXPLAIN SELECT id FROM finance.recurrence_occurrences "
                    "WHERE recurrence_id = :rule AND status = 'PENDING' "
                    "AND scheduled_date >= :d"
                ),
                {"rule": rules[0].id, "d": date(2026, 10, 6)},
            )
        )
    # Served by indexes (the window by period, the pending step by rule/pending),
    # never by a scan of the whole table.
    window_indexes = (
        "ix_finance_recurrence_occurrences_period",
        "ix_finance_recurrence_occurrences_rule",
    )
    assert any(name in plan for name in window_indexes), plan
    assert "Seq Scan on recurrence_occurrences" not in pending_plan, pending_plan
    assert any(
        name in pending_plan
        for name in (
            "ix_finance_recurrence_occurrences_pending",
            "ix_finance_recurrence_occurrences_rule",
        )
    ), pending_plan
