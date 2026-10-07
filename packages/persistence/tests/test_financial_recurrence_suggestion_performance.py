"""Cost proofs for the derived recurrence suggestions (ADR-0028).

The detector scans one bounded window of realized Movements under forced RLS. The
number of statements never depends on how many Movements, accounts or suggestions
exist, a large household finishes well inside a generous ceiling, and a scan that
would exceed its cap fails explicitly instead of returning a truncated answer.
"""

from __future__ import annotations

import time
from datetime import date
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pytest
from meufinanceiro_finance import SUGGESTION_SCAN_MAX
from sqlalchemy import event, text

from meufinanceiro_persistence.financial_recurrence_suggestion_store import (
    FinancialRecurrenceSuggestionLimitError,
    FinancialRecurrenceSuggestionStore,
)

if TYPE_CHECKING:
    from conftest import BudgetWorld

_TODAY = date(2026, 10, 20)


def _bulk(
    world: BudgetWorld,
    account_id: UUID,
    *,
    rows: int,
    start: str,
    span: int,
    prefix: str = "bulk",
) -> None:
    """Insert ``rows`` realized EXPENSE Movements with unique descriptions."""
    with world.engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text(
                """
                INSERT INTO finance.movements (
                    id, installation_id, residence_id, account_id, currency, amount,
                    result_effect, role, effective_date, competence_date, description,
                    created_by_operator_id, idempotency_key, request_digest, created_at
                )
                SELECT gen_random_uuid(), :i, :r, :a, 'BRL', -10, 'EXPENSE',
                       'STANDARD', CAST(:start AS date) + (g % :span),
                       CAST(:start AS date) + (g % :span), :p || ' ' || g, :o,
                       gen_random_uuid(), md5(g::text) || md5(g::text), now()
                FROM generate_series(1, :n) g
                """
            ),
            {
                "i": world.installation_id,
                "r": world.residence_id,
                "a": account_id,
                "o": world.owner_id,
                "n": rows,
                "start": start,
                "span": span,
                "p": prefix,
            },
        )


def _subscriptions(world: BudgetWorld, accounts: list[UUID], count: int) -> None:
    """``count`` three-month patterns spread over the accounts (Aug/Sep/Oct)."""
    with world.engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        for index in range(count):
            for month in (8, 9, 10):
                connection.execute(
                    text(
                        """
                        INSERT INTO finance.movements (
                            id, installation_id, residence_id, account_id, currency,
                            amount, result_effect, role, effective_date,
                            competence_date, description, created_by_operator_id,
                            idempotency_key, request_digest, created_at
                        ) VALUES (
                            gen_random_uuid(), :i, :r, :a, 'BRL', :amount, 'EXPENSE',
                            'STANDARD', :d, :d, CAST(:desc AS varchar), :o,
                            gen_random_uuid(),
                            md5(CAST(:desc AS text)) || md5(CAST(:desc AS text)),
                            now()
                        )
                        """
                    ),
                    {
                        "i": world.installation_id,
                        "r": world.residence_id,
                        "a": accounts[index % len(accounts)],
                        "o": world.owner_id,
                        "amount": -(10 + index),
                        "d": date(2026, month, 10),
                        "desc": f"Assinatura {index}",
                    },
                )


class _Counter:
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


def test_a_large_household_costs_a_fixed_number_of_statements_and_little_time(
    budget_world: BudgetWorld,
) -> None:
    accounts = [budget_world.account(name=f"Conta {n}") for n in range(4)]
    store = FinancialRecurrenceSuggestionStore(budget_world.runtime)
    scope = budget_world.scope()

    def read() -> tuple[int, int, float]:
        started = time.perf_counter()
        with _Counter(budget_world) as counter:
            found = store.list_suggestions(**scope, today=_TODAY)
        return counter.count, len(found), time.perf_counter() - started

    small_statements, small_found, _ = read()
    for index, account in enumerate(accounts):
        _bulk(
            budget_world,
            account,
            rows=1500,
            start="2025-11-01",
            span=354,
            prefix=f"avulso{index}",
        )
    _subscriptions(budget_world, accounts, 40)
    with budget_world.engine.begin() as connection:
        connection.execute(text("ANALYZE finance.movements"))

    statements, found, elapsed = read()

    assert (small_statements, small_found) == (6, 0)
    assert found == 40
    # context, membership, scan, reversed ids, linked ids, rules, one decisions lookup
    assert statements == 7
    # A generous ceiling that only a runaway plan or an N+1 can break (RLS forced).
    assert elapsed < 5.0, elapsed


def test_a_scan_over_the_cap_fails_explicitly_and_never_truncates(
    budget_world: BudgetWorld,
) -> None:
    account = budget_world.account()
    _bulk(
        budget_world,
        account,
        rows=SUGGESTION_SCAN_MAX + 1,
        start="2025-11-01",
        span=354,
    )
    store = FinancialRecurrenceSuggestionStore(budget_world.runtime)
    started = time.perf_counter()
    with pytest.raises(FinancialRecurrenceSuggestionLimitError):
        store.list_suggestions(**budget_world.scope(), today=_TODAY)
    assert time.perf_counter() - started < 30.0
