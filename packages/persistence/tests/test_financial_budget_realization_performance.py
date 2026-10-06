"""Plan and cost proofs for the derived budget realization on a large ledger.

Volume is built with raw SQL as the owner role (triggers off, only to be fast);
every measured read goes through the non-superuser runtime role with forced RLS.
The claim is about *shape*, not a stopwatch: the cost of one budget month follows
the Movements of that month, never the size of the whole ledger, and no step is
repeated per budget line, category or Movement.
"""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from meufinanceiro_finance import (
    FinancialBudgetDateBasis,
    FinancialBudgetDraft,
    FinancialBudgetLineDraft,
    FinancialBudgetRecord,
    FinancialResultEffect,
    FinancialVisibilityScope,
    Money,
    new_financial_idempotency_key,
)
from sqlalchemy import event, text

from meufinanceiro_persistence.financial_budget_realization_store import (
    FinancialBudgetRealizationStore,
)
from meufinanceiro_persistence.financial_budget_store import FinancialBudgetStore

if TYPE_CHECKING:
    from conftest import BudgetWorld

_MONTH = date(2025, 3, 1)
_CATEGORIES = 20


def _seed(
    world: BudgetWorld,
    account_id: UUID,
    categories: list[UUID],
    *,
    rows: int,
    start: str,
    span: int,
) -> None:
    """Insert ``rows`` classifiable Movements (70% classified, ~2% reversed)."""
    category_array = ",".join(f"'{category}'" for category in categories)
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
                       CASE WHEN g % 4 = 0 THEN 10 ELSE -10 END,
                       CASE WHEN g % 4 = 0 THEN 'INCOME' ELSE 'EXPENSE' END,
                       'STANDARD', CAST(:start AS date) + (g % :span),
                       CAST(:start AS date) + (g % :span), 'bulk ' || g, :o,
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
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO finance.movement_allocation_sets (
                    id, installation_id, residence_id, movement_id, revision,
                    supersedes_id, created_by_operator_id, idempotency_key,
                    request_digest, created_at
                )
                SELECT gen_random_uuid(), installation_id, residence_id, id, 1, NULL,
                       created_by_operator_id, gen_random_uuid(),
                       md5(id::text) || md5(id::text), now()
                FROM finance.movements
                WHERE residence_id = :r AND role = 'STANDARD'
                  AND NOT EXISTS (
                      SELECT 1 FROM finance.movement_allocation_sets s
                      WHERE s.movement_id = finance.movements.id)
                  AND (hashtext(id::text) % 10) < 7
                """
            ),
            {"r": world.residence_id},
        )
        connection.execute(
            text(
                f"""
                INSERT INTO finance.movement_allocations (
                    id, allocation_set_id, installation_id, residence_id,
                    movement_id, category_id, currency, amount, created_at
                )
                SELECT gen_random_uuid(), s.id, s.installation_id, s.residence_id,
                       s.movement_id,
                       (ARRAY[{category_array}]::uuid[])[
                           1 + (abs(hashtext(s.id::text)) % {len(categories)})],
                       'BRL', m.amount, now()
                FROM finance.movement_allocation_sets s
                JOIN finance.movements m ON m.id = s.movement_id
                WHERE s.residence_id = :r AND NOT EXISTS (
                    SELECT 1 FROM finance.movement_allocations a
                    WHERE a.allocation_set_id = s.id)
                """
            ),
            {"r": world.residence_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO finance.movements (
                    id, installation_id, residence_id, account_id, currency, amount,
                    result_effect, role, effective_date, competence_date,
                    description, reversal_of_id, reversal_target_role,
                    reversal_reason, created_by_operator_id, idempotency_key,
                    request_digest, created_at
                )
                SELECT gen_random_uuid(), installation_id, residence_id, account_id,
                       currency, -amount, result_effect, 'REVERSAL',
                       effective_date + 3, competence_date + 3, NULL, id, 'STANDARD',
                       'bulk reversal', created_by_operator_id, gen_random_uuid(),
                       md5(id::text) || md5(id::text), now()
                FROM finance.movements m
                WHERE residence_id = :r AND role = 'STANDARD'
                  AND (hashtext(id::text) % 50) = 0
                  AND NOT EXISTS (
                      SELECT 1 FROM finance.movements x WHERE x.reversal_of_id = m.id)
                """
            ),
            {"r": world.residence_id},
        )
        for table in (
            "movements",
            "movement_allocation_sets",
            "movement_allocations",
        ):
            connection.execute(text(f"ANALYZE finance.{table}"))


def _budget(
    world: BudgetWorld,
    categories: list[UUID],
    basis: FinancialBudgetDateBasis = FinancialBudgetDateBasis.CASH,
) -> FinancialBudgetRecord:
    lines = tuple(
        FinancialBudgetLineDraft(
            category,
            FinancialResultEffect.EXPENSE
            if index % 2 == 0
            else FinancialResultEffect.INCOME,
            Money(Decimal("100"), "BRL"),
        )
        for index, category in enumerate(categories)
    )
    return FinancialBudgetStore(world.runtime).create_budget(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialBudgetDraft(
            name="Plano",
            visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
            currency="BRL",
            period_start=_MONTH,
            date_basis=basis,
            lines=lines,
        ),
    )


def _explain(world: BudgetWorld, budget_id: UUID, marker: str) -> dict[str, Any]:
    """EXPLAIN ANALYZE of the one statement of the read that mentions ``marker``."""
    captured: list[tuple[str, Any]] = []

    def capture(_conn: Any, _cursor: Any, statement: str, params: Any, *_rest: Any):
        if marker in statement:
            captured.append((statement, params))

    event.listen(world.runtime, "before_cursor_execute", capture)
    try:
        FinancialBudgetRealizationStore(world.runtime).read_realization(
            **world.scope(), budget_id=budget_id
        )
    finally:
        event.remove(world.runtime, "before_cursor_execute", capture)
    assert len(captured) == 1, marker
    statement, params = captured[0]
    with world.runtime.begin() as connection:
        connection.execute(
            text(
                "SELECT set_config('app.current_installation_id', :i, true), "
                "set_config('app.current_residence_id', :r, true), "
                "set_config('app.current_operator_id', :o, true)"
            ),
            {
                "i": str(world.installation_id),
                "r": str(world.residence_id),
                "o": str(world.owner_id),
            },
        )
        row = connection.exec_driver_sql(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, params
        ).scalar_one()
    plan = row[0] if isinstance(row, list) else row
    assert isinstance(plan, dict)
    return plan


def _nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
    found = [node]
    for child in node.get("Plans", []):
        found.extend(_nodes(child))
    return found


def _buffers(plan: dict[str, Any]) -> int:
    top = plan["Plan"]
    return int(top.get("Shared Hit Blocks", 0)) + int(top.get("Shared Read Blocks", 0))


def test_realized_and_coverage_follow_the_month_not_the_ledger(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    account = world.account()
    categories = [world.category(f"Categoria {index}") for index in range(_CATEGORIES)]
    # 30k Movements spread over ~1000 days: about 900 land in the budget month.
    _seed(world, account, categories, rows=30_000, start="2024-01-01", span=1000)
    budget = _budget(world, categories)

    realized = _explain(world, budget.id, "budget-realized")
    coverage = _explain(world, budget.id, "budget-coverage")
    baseline = {"realized": _buffers(realized), "coverage": _buffers(coverage)}

    # Plan shape: no table is swept, every access is an index access.
    for plan in (realized, coverage):
        nodes = _nodes(plan["Plan"])
        assert not [
            node
            for node in nodes
            if node["Node Type"] == "Seq Scan"
            and node.get("Relation Name")
            in {"movements", "movement_allocations", "movement_allocation_sets"}
        ]
        # The month is reached through a date-ranged index, not the residence.
        month_scans = [
            node
            for node in nodes
            if node.get("Relation Name") == "movements"
            and "effective_date" in str(node.get("Index Cond", ""))
        ]
        assert month_scans

    # Triple the ledger with Movements that are all outside the budget month.
    _seed(world, account, categories, rows=60_000, start="2021-01-01", span=700)
    grown_realized = _explain(world, budget.id, "budget-realized")
    grown_coverage = _explain(world, budget.id, "budget-coverage")
    # The cost follows the month: the window is unchanged, so a ledger three
    # times as large may add only index-descent noise, never a proportional cost.
    assert _buffers(grown_realized) <= baseline["realized"] * 1.6
    assert _buffers(grown_coverage) <= baseline["coverage"] * 1.6


def test_one_budget_month_of_a_large_ledger_reads_quickly_and_correctly(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    account = world.account()
    categories = [world.category(f"Categoria {index}") for index in range(_CATEGORIES)]
    _seed(world, account, categories, rows=60_000, start="2024-01-01", span=1000)
    budget = _budget(world, categories)
    store = FinancialBudgetRealizationStore(world.runtime)

    started = time.perf_counter()
    _, realization = store.read_realization(**world.scope(), budget_id=budget.id)
    elapsed = time.perf_counter() - started

    # One month of a 60k ledger (~1.9k Movements in the window): about 0.1 s measured
    # under forced RLS, with no per-line, per-category or per-Movement round trip.
    assert elapsed < 1.5
    assert realization.rows
    assert all(isinstance(row.amount, Decimal) for row in realization.rows)
    assert realization.unclassified_expense.count > 0
    assert realization.unclassified_income.count > 0

    # Fixed number of statements however large the ledger.
    statements: list[str] = []

    def record(_c: Any, _cur: Any, statement: str, *_rest: Any) -> None:
        statements.append(statement)

    event.listen(world.runtime, "before_cursor_execute", record)
    try:
        store.read_realization(**world.scope(), budget_id=budget.id)
    finally:
        event.remove(world.runtime, "before_cursor_execute", record)
    assert len(statements) <= 8
