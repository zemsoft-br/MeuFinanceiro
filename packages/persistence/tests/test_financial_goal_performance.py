"""Cost proofs for goal allocation and summary on a large ledger.

Volume is built with raw SQL as the owner role (triggers off, only to be fast);
every measured call goes through the non-superuser runtime role with forced RLS.
The claim is about *shape*: reusing the canonical balance makes an allocation or a
summary follow the Movements of the accounts it touches, never the size of the whole
ledger, and the number of statements never follows events, Movements or goals.
"""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from meufinanceiro_finance import (
    GOAL_ACCOUNTS_MAX,
    FinancialGoalAllocationDraft,
    FinancialGoalDraft,
    FinancialGoalEventKind,
    FinancialOpeningBalanceDraft,
    FinancialVisibilityScope,
    Money,
    new_financial_idempotency_key,
)
from sqlalchemy import event, text

from meufinanceiro_persistence.financial_goal_store import FinancialGoalStore
from meufinanceiro_persistence.financial_opening_balance_store import (
    FinancialOpeningBalanceStore,
)

if TYPE_CHECKING:
    from conftest import BudgetWorld

_ALLOCATE = FinancialGoalEventKind.ALLOCATE


def _money(amount: str) -> Money:
    return Money(Decimal(amount), "BRL")


def _funded(world: BudgetWorld) -> UUID:
    account = world.account()
    FinancialOpeningBalanceStore(world.runtime).create_opening_balance(
        **world.scope(),
        account_id=account,
        draft=FinancialOpeningBalanceDraft(
            amount=_money("1000000"), effective_date=date(2020, 1, 1)
        ),
    )
    return account


def _seed(world: BudgetWorld, account_id: UUID, rows: int) -> None:
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
                SELECT gen_random_uuid(), :i, :r, :a, 'BRL',
                       CASE WHEN g % 4 = 0 THEN 10 ELSE -1 END,
                       CASE WHEN g % 4 = 0 THEN 'INCOME' ELSE 'EXPENSE' END,
                       'STANDARD', DATE '2021-01-01' + (g % 900),
                       DATE '2021-01-01' + (g % 900), 'bulk ' || g, :o,
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
            },
        )


def _goal(world: BudgetWorld) -> UUID:
    return (
        FinancialGoalStore(world.runtime)
        .create_goal(
            **world.scope(),
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialGoalDraft(
                title="Reserva",
                description=None,
                visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
                target=_money("900000"),
                target_date=None,
            ),
        )
        .id
    )


def _allocate(world: BudgetWorld, goal_id: UUID, account_id: UUID, amount: str) -> None:
    FinancialGoalStore(world.runtime).allocate(
        **world.scope(),
        goal_id=goal_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialGoalAllocationDraft(_ALLOCATE, account_id, _money(amount)),
    )


def _timed(call: Any) -> float:
    started = time.perf_counter()
    call()
    return time.perf_counter() - started


def _statements(world: BudgetWorld, call: Any) -> int:
    statements: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    event.listen(world.runtime, "before_cursor_execute", record)
    try:
        call()
    finally:
        event.remove(world.runtime, "before_cursor_execute", record)
    return len(statements)


def test_allocation_and_summary_cost_follows_the_account_not_the_ledger(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    goal = _goal(world)
    busy = _funded(world)
    _seed(world, busy, 20_000)
    quiet = _funded(world)
    _allocate(world, goal, quiet, "1")  # warm up pools and plans

    quiet_allocation = _timed(lambda: _allocate(world, goal, quiet, "1"))
    busy_allocation = _timed(lambda: _allocate(world, goal, busy, "1"))

    # A very large ledger on *other* accounts does not slow an allocation down.
    for _ in range(3):
        _seed(world, _funded(world), 20_000)
    quiet_after_noise = _timed(lambda: _allocate(world, goal, quiet, "1"))

    print(
        f"allocation quiet={quiet_allocation:.3f}s busy(20k)={busy_allocation:.3f}s "
        f"quiet-after-60k-noise={quiet_after_noise:.3f}s"
    )
    assert busy_allocation < 5.0
    assert quiet_after_noise < max(0.5, quiet_allocation * 4)


def test_summary_with_the_maximum_accounts_on_a_large_ledger(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    goal = _goal(world)
    store = FinancialGoalStore(world.runtime)
    accounts = [_funded(world) for _ in range(GOAL_ACCOUNTS_MAX)]
    for account in accounts:
        _seed(world, account, 2_000)  # 50k Movements across the goal's accounts
        _allocate(world, goal, account, "1")
    other = _goal(world)
    for account in accounts[:5]:
        _allocate(world, other, account, "1")

    elapsed = _timed(lambda: store.read_goal_facts(**world.scope(), goal_id=goal))
    statements = _statements(
        world, lambda: store.read_goal_facts(**world.scope(), goal_id=goal)
    )
    list_elapsed = _timed(lambda: store.list_goals(**world.scope()))

    print(
        f"summary 25 accounts / 50k Movements: {elapsed:.3f}s, "
        f"{statements} statements; list: {list_elapsed:.3f}s"
    )
    # Context + membership + goal + events + totals, then 3 reads per account
    # (account, opening balance, Movements) plus the account set-up statements.
    assert statements <= 8 + 3 * GOAL_ACCOUNTS_MAX
    assert elapsed < 10.0
    assert list_elapsed < 1.0
