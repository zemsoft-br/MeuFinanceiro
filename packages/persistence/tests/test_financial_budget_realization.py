"""PostgreSQL-backed proofs for the derived realized amounts and coverage.

Realized values are never stored: every proof classifies, revises or reverses
through the real ledger/classification stores and then reads the budget again.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pytest
from meufinanceiro_finance import (
    FinancialBudgetDateBasis,
    FinancialBudgetDraft,
    FinancialBudgetLineDraft,
    FinancialBudgetRealization,
    FinancialBudgetRecord,
    FinancialMovementAllocationDraft,
    FinancialMovementAllocationRevisionDraft,
    FinancialMovementAllocationSetDraft,
    FinancialMovementDraft,
    FinancialMovementReversalDraft,
    FinancialResultEffect,
    FinancialTransferDraft,
    FinancialVisibilityScope,
    Money,
    new_financial_idempotency_key,
)
from sqlalchemy import event, func, select

from meufinanceiro_persistence.financial_budget_realization_store import (
    FinancialBudgetRealizationStore,
)
from meufinanceiro_persistence.financial_budget_store import (
    FinancialBudgetNotFoundError,
    FinancialBudgetStore,
)
from meufinanceiro_persistence.financial_movement_allocation_schema import (
    financial_movement_allocation_sets,
    financial_movement_allocations,
)
from meufinanceiro_persistence.financial_movement_allocation_store import (
    FinancialMovementAllocationStore,
)
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import FinancialMovementStore
from meufinanceiro_persistence.financial_transfer_store import FinancialTransferStore

if TYPE_CHECKING:
    from conftest import BudgetWorld

_OCT = date(2026, 10, 1)
_NOV = date(2026, 11, 1)
_EXPENSE = FinancialResultEffect.EXPENSE
_INCOME = FinancialResultEffect.INCOME
_HOUSEHOLD = FinancialVisibilityScope.HOUSEHOLD
_PERSONAL = FinancialVisibilityScope.PERSONAL


def _money(amount: str, currency: str = "BRL") -> Money:
    return Money(Decimal(amount), currency)


def _budget(
    world: BudgetWorld,
    lines: dict[tuple[UUID, FinancialResultEffect], str],
    *,
    scope: FinancialVisibilityScope = _HOUSEHOLD,
    basis: FinancialBudgetDateBasis = FinancialBudgetDateBasis.CASH,
    period: date = _OCT,
    currency: str = "BRL",
    operator_id: UUID | None = None,
) -> FinancialBudgetRecord:
    return FinancialBudgetStore(world.runtime).create_budget(
        **world.scope(operator_id),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialBudgetDraft(
            name="Plano",
            visibility_scope=scope,
            currency=currency,
            period_start=period,
            date_basis=basis,
            lines=tuple(
                FinancialBudgetLineDraft(category, effect, _money(amount, currency))
                for (category, effect), amount in lines.items()
            ),
        ),
    )


def _move(
    world: BudgetWorld,
    account_id: UUID,
    amount: str,
    *,
    effective: date = date(2026, 10, 10),
    competence: date | None = None,
    currency: str = "BRL",
    operator_id: UUID | None = None,
) -> UUID:
    effect = _INCOME if Decimal(amount) > 0 else _EXPENSE
    return (
        FinancialMovementStore(world.runtime)
        .create_movement(
            **world.scope(operator_id),
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementDraft(
                account_id=account_id,
                amount=_money(amount, currency),
                result_effect=effect,
                effective_date=effective,
                competence_date=competence or effective,
                description="Sintético",
            ),
        )
        .id
    )


def _classify(
    world: BudgetWorld,
    movement_id: UUID,
    shares: dict[UUID, str],
    currency: str = "BRL",
) -> UUID:
    return (
        FinancialMovementAllocationStore(world.runtime)
        .create_allocation_set(
            **world.scope(),
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementAllocationSetDraft(
                movement_id=movement_id,
                allocations=tuple(
                    FinancialMovementAllocationDraft(category, _money(amount, currency))
                    for category, amount in shares.items()
                ),
            ),
        )
        .id
    )


def _reclassify(
    world: BudgetWorld, movement_id: UUID, current_set: UUID, shares: dict[UUID, str]
) -> UUID:
    return (
        FinancialMovementAllocationStore(world.runtime)
        .revise_allocation_set(
            **world.scope(),
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementAllocationRevisionDraft(
                movement_id=movement_id,
                supersedes_id=current_set,
                allocations=tuple(
                    FinancialMovementAllocationDraft(category, _money(amount))
                    for category, amount in shares.items()
                ),
            ),
        )
        .id
    )


def _reverse(
    world: BudgetWorld,
    movement_id: UUID,
    *,
    effective: date = date(2026, 10, 20),
    competence: date | None = None,
) -> UUID:
    return (
        FinancialMovementStore(world.runtime)
        .reverse_movement(
            **world.scope(),
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialMovementReversalDraft(
                movement_id=movement_id,
                effective_date=effective,
                competence_date=competence or effective,
                reason="Sintético",
            ),
        )
        .id
    )


def _read(
    world: BudgetWorld, budget: FinancialBudgetRecord, operator_id: UUID | None = None
) -> FinancialBudgetRealization:
    _, realization = FinancialBudgetRealizationStore(world.runtime).read_realization(
        **world.scope(operator_id), budget_id=budget.id
    )
    return realization


def _realized(
    realization: FinancialBudgetRealization,
) -> dict[tuple[UUID, str], Decimal]:
    return {(r.category_id, r.result_effect.value): r.amount for r in realization.rows}


def _ledger_snapshot(world: BudgetWorld) -> list[tuple[Any, ...]]:
    with world.engine.begin() as connection:
        movements = connection.execute(
            select(
                financial_movements.c.id,
                financial_movements.c.account_id,
                financial_movements.c.amount,
                financial_movements.c.currency,
                financial_movements.c.result_effect,
                financial_movements.c.role,
                financial_movements.c.effective_date,
                financial_movements.c.competence_date,
            ).order_by(financial_movements.c.id)
        ).all()
    return [tuple(row) for row in movements]


@pytest.fixture
def setup(budget_world: BudgetWorld) -> dict[str, UUID]:
    return {
        "account": budget_world.account(),
        "market": budget_world.category("Mercado"),
        "salary": budget_world.category("Salário"),
        "leisure": budget_world.category("Lazer"),
    }


# --- the issue's vertical smoke -----------------------------------------------


def test_smoke_planned_vs_realized_coverage_split_reclassification_and_reversal(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    world, account = budget_world, setup["account"]
    market, salary, leisure = setup["market"], setup["salary"], setup["leisure"]
    budget = _budget(world, {(market, _EXPENSE): "1000", (salary, _INCOME): "5000"})

    groceries = _move(world, account, "-300")
    _classify(world, groceries, {market: "-300"})
    paycheck = _move(world, account, "4500")
    _classify(world, paycheck, {salary: "4500"})
    _move(world, account, "-100")  # unclassified: only in coverage

    first = _read(world, budget)
    assert _realized(first) == {
        (market, "EXPENSE"): Decimal("300"),
        (salary, "INCOME"): Decimal("4500"),
    }
    assert first.unclassified_expense.count == 1
    assert first.unclassified_expense.amount == Decimal("100")
    assert first.unclassified_income.count == 0
    assert first.unclassified_income.amount == Decimal(0)

    split = _move(world, account, "-200")
    split_set = _classify(world, split, {market: "-120", leisure: "-80"})
    assert _realized(_read(world, budget))[(market, "EXPENSE")] == Decimal("420")

    before = _ledger_snapshot(world)
    _reclassify(world, split, split_set, {leisure: "-200"})
    after_reclass = _read(world, budget)
    assert _realized(after_reclass)[(market, "EXPENSE")] == Decimal("300")
    assert (
        _ledger_snapshot(world) == before
    )  # reclassification never touches the ledger

    _reverse(world, groceries)
    final = _read(world, budget)
    assert _realized(final).get((market, "EXPENSE"), Decimal(0)) == Decimal("0")
    assert _realized(final)[(salary, "INCOME")] == Decimal("4500")
    assert final.unclassified_expense.count == 1


# --- classification semantics ---------------------------------------------------


def test_split_counts_only_the_budgeted_categorys_share(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    movement = _move(budget_world, setup["account"], "-200")
    _classify(
        budget_world, movement, {setup["market"]: "-120", setup["leisure"]: "-80"}
    )
    both = _budget(
        budget_world,
        {(setup["market"], _EXPENSE): "1000", (setup["leisure"], _EXPENSE): "500"},
    )
    realized = _realized(_read(budget_world, both))
    assert realized == {
        (setup["market"], "EXPENSE"): Decimal("120"),
        (setup["leisure"], "EXPENSE"): Decimal("80"),
    }


def test_realized_is_a_positive_magnitude_for_expense_and_income(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    _classify(
        budget_world,
        _move(budget_world, setup["account"], "-12.34567889"),
        {setup["market"]: "-12.34567889"},
    )
    _classify(
        budget_world,
        _move(budget_world, setup["account"], "0.00000001"),
        {setup["salary"]: "0.00000001"},
    )
    budget = _budget(
        budget_world,
        {(setup["market"], _EXPENSE): "100", (setup["salary"], _INCOME): "1"},
    )
    realized = _realized(_read(budget_world, budget))
    assert realized[(setup["market"], "EXPENSE")] == Decimal("12.34567889")
    assert realized[(setup["salary"], "INCOME")] == Decimal("0.00000001")
    assert all(isinstance(value, Decimal) and value > 0 for value in realized.values())


def test_a_line_only_counts_its_own_effect_for_the_same_category(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    # A refund (INCOME) classified under the expense category must not offset the
    # EXPENSE line: the income line, if planned, counts it separately.
    spend = _move(budget_world, setup["account"], "-50")
    _classify(budget_world, spend, {setup["market"]: "-50"})
    refund = _move(budget_world, setup["account"], "20")
    _classify(budget_world, refund, {setup["market"]: "20"})
    budget = _budget(
        budget_world,
        {(setup["market"], _EXPENSE): "100", (setup["market"], _INCOME): "100"},
    )
    assert _realized(_read(budget_world, budget)) == {
        (setup["market"], "EXPENSE"): Decimal("50"),
        (setup["market"], "INCOME"): Decimal("20"),
    }


def test_reclassification_moves_the_amount_without_touching_the_ledger(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    movement = _move(budget_world, setup["account"], "-80")
    first_set = _classify(budget_world, movement, {setup["market"]: "-80"})
    budget = _budget(
        budget_world,
        {(setup["market"], _EXPENSE): "100", (setup["leisure"], _EXPENSE): "100"},
    )
    assert _realized(_read(budget_world, budget)) == {
        (setup["market"], "EXPENSE"): Decimal("80")
    }
    ledger = _ledger_snapshot(budget_world)
    _reclassify(budget_world, movement, first_set, {setup["leisure"]: "-80"})
    assert _realized(_read(budget_world, budget)) == {
        (setup["leisure"], "EXPENSE"): Decimal("80")
    }
    assert _ledger_snapshot(budget_world) == ledger


def test_only_the_current_allocation_set_counts(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    movement = _move(budget_world, setup["account"], "-60")
    first = _classify(budget_world, movement, {setup["market"]: "-60"})
    second = _reclassify(
        budget_world, movement, first, {setup["market"]: "-10", setup["leisure"]: "-50"}
    )
    _reclassify(budget_world, movement, second, {setup["market"]: "-60"})
    budget = _budget(budget_world, {(setup["market"], _EXPENSE): "100"})
    assert _realized(_read(budget_world, budget)) == {
        (setup["market"], "EXPENSE"): Decimal("60")
    }
    with budget_world.engine.begin() as connection:
        sets = connection.scalar(
            select(func.count()).select_from(financial_movement_allocation_sets)
        )
        shares = connection.scalar(
            select(func.count()).select_from(financial_movement_allocations)
        )
    assert (sets, shares) == (3, 4)  # history preserved, only the leaf counts


# --- currency, neutrality, audience ---------------------------------------------


def test_other_currency_movements_are_out(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    usd_account = budget_world.account(currency="USD", name="Dólar")
    usd = _move(budget_world, usd_account, "-70", currency="USD")
    _classify(budget_world, usd, {setup["market"]: "-70"}, currency="USD")
    brl = _move(budget_world, setup["account"], "-30")
    _classify(budget_world, brl, {setup["market"]: "-30"})
    brl_budget = _budget(budget_world, {(setup["market"], _EXPENSE): "100"})
    usd_budget = _budget(
        budget_world, {(setup["market"], _EXPENSE): "100"}, currency="USD"
    )
    assert _realized(_read(budget_world, brl_budget)) == {
        (setup["market"], "EXPENSE"): Decimal("30")
    }
    assert _realized(_read(budget_world, usd_budget)) == {
        (setup["market"], "EXPENSE"): Decimal("70")
    }
    # An unclassified USD expense is not BRL coverage either.
    _move(budget_world, usd_account, "-5", currency="USD")
    assert _read(budget_world, brl_budget).unclassified_expense.count == 0
    assert _read(budget_world, usd_budget).unclassified_expense.count == 1


def test_neutral_transfers_never_count_or_pend(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    destination = budget_world.account(name="Poupança")
    FinancialTransferStore(budget_world.runtime).create_transfer(
        **budget_world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialTransferDraft(
            source_account_id=setup["account"],
            destination_account_id=destination,
            magnitude=_money("500"),
            effective_date=date(2026, 10, 12),
            competence_date=date(2026, 10, 12),
            description="Transferência",
        ),
    )
    budget = _budget(budget_world, {(setup["market"], _EXPENSE): "100"})
    realization = _read(budget_world, budget)
    assert realization.rows == ()
    assert realization.unclassified_expense.count == 0
    assert realization.unclassified_income.count == 0


def test_household_budget_ignores_personal_accounts_and_is_identical_for_members(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    personal_account = budget_world.account(household=False, name="Pessoal")
    hidden = _move(budget_world, personal_account, "-999")
    _classify(budget_world, hidden, {setup["market"]: "-999"})
    shared = _move(budget_world, setup["account"], "-40")
    _classify(budget_world, shared, {setup["market"]: "-40"})
    _move(budget_world, personal_account, "-7")  # personal unclassified

    budget = _budget(budget_world, {(setup["market"], _EXPENSE): "100"})
    owner_view = _read(budget_world, budget)
    member_view = _read(budget_world, budget, operator_id=budget_world.member_id)
    assert _realized(owner_view) == {(setup["market"], "EXPENSE"): Decimal("40")}
    assert owner_view == member_view
    assert owner_view.unclassified_expense.count == 0


def test_personal_budget_counts_only_the_owners_personal_accounts(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    mine = budget_world.category("Meu mercado", household=False)
    personal_account = budget_world.account(household=False, name="Pessoal")
    movement = _move(budget_world, personal_account, "-25")
    _classify(budget_world, movement, {mine: "-25"})
    # Household activity must not leak into a personal plan.
    household_spend = _move(budget_world, setup["account"], "-1000")
    _classify(budget_world, household_spend, {setup["market"]: "-1000"})
    _move(budget_world, setup["account"], "-3")

    budget = _budget(budget_world, {(mine, _EXPENSE): "100"}, scope=_PERSONAL)
    realization = _read(budget_world, budget)
    assert _realized(realization) == {(mine, "EXPENSE"): Decimal("25")}
    assert realization.unclassified_expense.count == 0


def test_a_member_cannot_read_another_members_personal_budget(
    budget_world: BudgetWorld,
) -> None:
    mine = budget_world.category("Meu mercado", household=False)
    budget = _budget(budget_world, {(mine, _EXPENSE): "100"}, scope=_PERSONAL)
    with pytest.raises(FinancialBudgetNotFoundError):
        _read(budget_world, budget, operator_id=budget_world.member_id)


# --- period and date basis ---------------------------------------------------------


@pytest.mark.parametrize(
    ("effective", "inside"),
    [
        (date(2026, 9, 30), False),
        (date(2026, 10, 1), True),
        (date(2026, 10, 31), True),
        (date(2026, 11, 1), False),
    ],
)
def test_month_boundaries_are_half_open(
    budget_world: BudgetWorld,
    setup: dict[str, UUID],
    effective: date,
    inside: bool,
) -> None:
    movement = _move(budget_world, setup["account"], "-10", effective=effective)
    _classify(budget_world, movement, {setup["market"]: "-10"})
    _move(budget_world, setup["account"], "-4", effective=effective)
    budget = _budget(budget_world, {(setup["market"], _EXPENSE): "100"})
    realization = _read(budget_world, budget)
    assert bool(realization.rows) is inside
    assert realization.unclassified_expense.count == (1 if inside else 0)


def test_cash_and_competence_place_the_same_movement_in_different_months(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    movement = _move(
        budget_world,
        setup["account"],
        "-90",
        effective=date(2026, 10, 31),
        competence=date(2026, 11, 2),
    )
    _classify(budget_world, movement, {setup["market"]: "-90"})
    lines = {(setup["market"], _EXPENSE): "100"}
    cash_oct = _budget(budget_world, lines, basis=FinancialBudgetDateBasis.CASH)
    cash_nov = _budget(
        budget_world, lines, basis=FinancialBudgetDateBasis.CASH, period=_NOV
    )
    comp_oct = _budget(budget_world, lines, basis=FinancialBudgetDateBasis.COMPETENCE)
    comp_nov = _budget(
        budget_world, lines, basis=FinancialBudgetDateBasis.COMPETENCE, period=_NOV
    )
    amount = {(setup["market"], "EXPENSE"): Decimal("90")}
    assert _realized(_read(budget_world, cash_oct)) == amount
    assert _realized(_read(budget_world, cash_nov)) == {}
    assert _realized(_read(budget_world, comp_oct)) == {}
    assert _realized(_read(budget_world, comp_nov)) == amount


# --- coverage ------------------------------------------------------------------------


def test_unclassified_is_counted_per_effect_and_never_attributed_to_a_line(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    _move(budget_world, setup["account"], "-100")
    _move(budget_world, setup["account"], "-0.50")
    _move(budget_world, setup["account"], "250")
    budget = _budget(
        budget_world,
        {(setup["market"], _EXPENSE): "100", (setup["salary"], _INCOME): "100"},
    )
    realization = _read(budget_world, budget)
    assert realization.rows == ()
    assert realization.unclassified_expense.count == 2
    assert realization.unclassified_expense.amount == Decimal("100.5")
    assert realization.unclassified_income.count == 1
    assert realization.unclassified_income.amount == Decimal("250")


def test_classifying_a_pending_movement_removes_it_from_coverage_on_the_next_read(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    movement = _move(budget_world, setup["account"], "-100")
    budget = _budget(budget_world, {(setup["market"], _EXPENSE): "500"})
    assert _read(budget_world, budget).unclassified_expense.count == 1
    _classify(budget_world, movement, {setup["market"]: "-100"})
    after = _read(budget_world, budget)
    assert after.unclassified_expense.count == 0
    assert _realized(after) == {(setup["market"], "EXPENSE"): Decimal("100")}


def test_coverage_uses_the_budget_date_basis(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    _move(
        budget_world,
        setup["account"],
        "-10",
        effective=date(2026, 10, 31),
        competence=date(2026, 11, 3),
    )
    lines = {(setup["market"], _EXPENSE): "100"}
    cash = _budget(budget_world, lines)
    competence = _budget(budget_world, lines, basis=FinancialBudgetDateBasis.COMPETENCE)
    assert _read(budget_world, cash).unclassified_expense.count == 1
    assert _read(budget_world, competence).unclassified_expense.count == 0


# --- reversals --------------------------------------------------------------------------


def test_full_reversal_in_the_same_month_undoes_the_impact_exactly_once(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    movement = _move(budget_world, setup["account"], "-300")
    _classify(budget_world, movement, {setup["market"]: "-300"})
    budget = _budget(budget_world, {(setup["market"], _EXPENSE): "1000"})
    assert _realized(_read(budget_world, budget)) == {
        (setup["market"], "EXPENSE"): Decimal("300")
    }
    _reverse(budget_world, movement)
    assert _realized(_read(budget_world, budget)) == {
        (setup["market"], "EXPENSE"): Decimal("0")
    }


def test_reversing_a_split_movement_undoes_each_share(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    movement = _move(budget_world, setup["account"], "-200")
    _classify(
        budget_world, movement, {setup["market"]: "-120", setup["leisure"]: "-80"}
    )
    _reverse(budget_world, movement)
    budget = _budget(
        budget_world,
        {(setup["market"], _EXPENSE): "100", (setup["leisure"], _EXPENSE): "100"},
    )
    assert _realized(_read(budget_world, budget)) == {
        (setup["market"], "EXPENSE"): Decimal("0"),
        (setup["leisure"], "EXPENSE"): Decimal("0"),
    }


def test_reversal_in_a_later_month_lands_in_the_reversal_month(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    movement = _move(budget_world, setup["account"], "-300")
    _classify(budget_world, movement, {setup["market"]: "-300"})
    _reverse(budget_world, movement, effective=date(2026, 11, 5))
    lines = {(setup["market"], _EXPENSE): "1000"}
    october = _budget(budget_world, lines)
    november = _budget(budget_world, lines, period=_NOV)
    assert _realized(_read(budget_world, october)) == {
        (setup["market"], "EXPENSE"): Decimal("300")
    }
    # The reversal undoes the original's impact on the reversal date: a credit.
    assert _realized(_read(budget_world, november)) == {
        (setup["market"], "EXPENSE"): Decimal("-300")
    }


def test_reversal_follows_the_date_basis_of_the_budget(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    movement = _move(
        budget_world,
        setup["account"],
        "-300",
        effective=date(2026, 10, 10),
        competence=date(2026, 10, 10),
    )
    _classify(budget_world, movement, {setup["market"]: "-300"})
    # Cash reversal in November, but the competence date stays in October.
    _reverse(
        budget_world,
        movement,
        effective=date(2026, 11, 2),
        competence=date(2026, 10, 28),
    )
    lines = {(setup["market"], _EXPENSE): "1000"}
    competence_oct = _budget(
        budget_world, lines, basis=FinancialBudgetDateBasis.COMPETENCE
    )
    cash_oct = _budget(budget_world, lines)
    assert _realized(_read(budget_world, competence_oct)) == {
        (setup["market"], "EXPENSE"): Decimal("0")
    }
    assert _realized(_read(budget_world, cash_oct)) == {
        (setup["market"], "EXPENSE"): Decimal("300")
    }


def test_reclassifying_a_reversed_original_moves_both_sides_together(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    movement = _move(budget_world, setup["account"], "-80")
    first = _classify(budget_world, movement, {setup["market"]: "-80"})
    _reverse(budget_world, movement)
    _reclassify(budget_world, movement, first, {setup["leisure"]: "-80"})
    budget = _budget(
        budget_world,
        {(setup["market"], _EXPENSE): "100", (setup["leisure"], _EXPENSE): "100"},
    )
    realized = _realized(_read(budget_world, budget))
    assert realized.get((setup["market"], "EXPENSE"), Decimal(0)) == 0
    assert realized[(setup["leisure"], "EXPENSE")] == 0


def test_reversal_of_income_undoes_income(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    movement = _move(budget_world, setup["account"], "4500")
    _classify(budget_world, movement, {setup["salary"]: "4500"})
    _reverse(budget_world, movement)
    budget = _budget(budget_world, {(setup["salary"], _INCOME): "5000"})
    assert _realized(_read(budget_world, budget)) == {
        (setup["salary"], "INCOME"): Decimal("0")
    }


def test_an_unclassified_pair_inside_the_month_cancels_in_the_coverage(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    movement = _move(budget_world, setup["account"], "-100")
    _reverse(budget_world, movement)
    budget = _budget(budget_world, {(setup["market"], _EXPENSE): "100"})
    realization = _read(budget_world, budget)
    assert realization.unclassified_expense.count == 0
    assert realization.unclassified_expense.amount == Decimal(0)


def test_a_cross_month_unclassified_reversal_is_flagged_in_its_own_month(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    movement = _move(budget_world, setup["account"], "-100")
    _reverse(budget_world, movement, effective=date(2026, 11, 5))
    lines = {(setup["market"], _EXPENSE): "100"}
    october = _read(budget_world, _budget(budget_world, lines))
    november = _read(budget_world, _budget(budget_world, lines, period=_NOV))
    assert (
        october.unclassified_expense.count,
        october.unclassified_expense.amount,
    ) == (
        1,
        Decimal("100"),
    )
    assert (
        november.unclassified_expense.count,
        november.unclassified_expense.amount,
    ) == (1, Decimal("-100"))


# --- no ledger effect, cost -------------------------------------------------------------------


def test_reading_and_planning_never_change_the_ledger(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    movement = _move(budget_world, setup["account"], "-300")
    _classify(budget_world, movement, {setup["market"]: "-300"})
    before = _ledger_snapshot(budget_world)
    budget = _budget(budget_world, {(setup["market"], _EXPENSE): "1000"})
    _read(budget_world, budget)
    _read(budget_world, budget, operator_id=budget_world.member_id)
    assert _ledger_snapshot(budget_world) == before
    assert len(before) == 1


def test_realization_costs_a_fixed_number_of_statements(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    budget = _budget(
        budget_world,
        {(setup["market"], _EXPENSE): "100", (setup["salary"], _INCOME): "100"},
    )

    def cost() -> int:
        statements: list[str] = []

        def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
            statements.append(statement)

        event.listen(budget_world.runtime, "before_cursor_execute", record)
        try:
            _read(budget_world, budget)
        finally:
            event.remove(budget_world.runtime, "before_cursor_execute", record)
        return len(statements)

    empty = cost()
    for index in range(25):
        movement = _move(budget_world, setup["account"], f"-{index + 1}")
        if index % 2:
            _classify(budget_world, movement, {setup["market"]: f"-{index + 1}"})
        if index % 5 == 0:
            _reverse(budget_world, movement)
    assert cost() == empty
    assert empty <= 8


def test_a_reversal_dated_before_its_original_is_flagged_in_its_own_month(
    budget_world: BudgetWorld, setup: dict[str, UUID]
) -> None:
    movement = _move(
        budget_world, setup["account"], "-100", effective=date(2026, 11, 10)
    )
    _reverse(budget_world, movement, effective=date(2026, 10, 25))
    lines = {(setup["market"], _EXPENSE): "100"}
    october = _read(budget_world, _budget(budget_world, lines))
    november = _read(budget_world, _budget(budget_world, lines, period=_NOV))
    assert (
        october.unclassified_expense.count,
        october.unclassified_expense.amount,
    ) == (
        1,
        Decimal("-100"),
    )
    assert (
        november.unclassified_expense.count,
        november.unclassified_expense.amount,
    ) == (1, Decimal("100"))
