"""Read-only derivation of a budget's realized amounts and classification coverage.

Nothing here is persisted, cached or locked: the realized value of a (category,
effect) is recomputed from ``finance.movements`` and the *current* allocation set
on every read, so reclassifying a Movement changes the next summary and nothing
else. The whole read is one REPEATABLE READ, read-only transaction (a consistent
snapshot of the budget row, its lines and the ledger) with a fixed number of
statements, independent of the number of Movements, categories or lines.

Reversal awareness without classifying REVERSAL (ADR-0022, ADR-0026): a REVERSAL
contributes the *negative* of the current allocation of the STANDARD Movement it
reverses, placed at the REVERSAL's own date according to the date basis. A full
reversal in the same month as its original therefore nets to exactly zero, once.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from meufinanceiro_finance import (
    FinancialBudgetCoverageSlice,
    FinancialBudgetDateBasis,
    FinancialBudgetRealization,
    FinancialBudgetRealizedRow,
    FinancialBudgetRecord,
    FinancialResultEffect,
    FinancialVisibilityScope,
    budget_period_end,
    validate_financial_resource_id,
)
from meufinanceiro_finance.movements import FinancialMovementRole
from sqlalchemy import (
    Connection,
    Engine,
    case,
    exists,
    func,
    select,
    union_all,
)
from sqlalchemy.exc import DBAPIError
from sqlalchemy.sql.expression import ColumnElement, Exists, FromClause, Select

from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.financial_budget_schema import financial_budget_lines
from meufinanceiro_persistence.financial_budget_store import (
    FinancialBudgetAccessError,
    FinancialBudgetNotFoundError,
    FinancialBudgetPersistenceError,
    _load_records,
    _prepare,
    _require_scope,
    _visible_row,
)
from meufinanceiro_persistence.financial_movement_allocation_schema import (
    financial_movement_allocation_sets,
    financial_movement_allocations,
)
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementAccessError,
)

_STANDARD = FinancialMovementRole.STANDARD.value
_REVERSAL = FinancialMovementRole.REVERSAL.value
_EFFECTS = (
    FinancialResultEffect.INCOME.value,
    FinancialResultEffect.EXPENSE.value,
)


class FinancialBudgetRealizationStore:
    """Compute the derived realized rows and coverage of one visible budget."""

    def __init__(self, engine: Engine) -> None:
        if not isinstance(engine, Engine):
            raise TypeError("engine must be SQLAlchemy Engine")
        self._engine = engine

    def read_realization(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        budget_id: UUID,
    ) -> tuple[FinancialBudgetRecord, FinancialBudgetRealization]:
        """Return the budget and its realization from one consistent snapshot.

        Fixed statement count: context (1), membership (1), budget (1), lines (1),
        realized rows (1) and coverage (1). Forced RLS still decides which
        Movements the operator may see; the explicit account filter additionally
        pins the audience to the budget's own scope.
        """
        _require_scope(installation_id, residence_id, operator_id)
        validate_financial_resource_id(budget_id)
        try:
            with self._engine.connect().execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True
            ) as connection:
                with connection.begin():
                    _prepare(connection, installation_id, residence_id, operator_id)
                    row = _visible_row(
                        connection, installation_id, residence_id, budget_id
                    )
                    if row is None:
                        raise FinancialBudgetNotFoundError("budget was not found")
                    record = _load_records(connection, [row])[0]
                    realization = _realization(connection, record, installation_id)
                    return record, realization
        except FinancialMovementAccessError:
            raise FinancialBudgetAccessError("budget access denied") from None
        except FinancialBudgetPersistenceError:
            raise
        except DBAPIError:
            raise FinancialBudgetPersistenceError(
                "budget realization could not be read"
            ) from None


def _realization(
    connection: Connection, budget: FinancialBudgetRecord, installation_id: UUID
) -> FinancialBudgetRealization:
    window = (budget.period_start, budget_period_end(budget.period_start))
    realized = connection.execute(
        _realized_statement(budget, installation_id, window)
    ).all()
    coverage = connection.execute(
        _coverage_statement(budget, installation_id, window)
    ).all()
    try:
        rows = tuple(
            FinancialBudgetRealizedRow(
                category_id=row.category_id,
                result_effect=FinancialResultEffect(row.result_effect),
                amount=Decimal(row.amount),
            )
            for row in realized
        )
        counts = {value: 0 for value in _EFFECTS}
        amounts = {value: Decimal(0) for value in _EFFECTS}
        for row in coverage:
            counts[row.result_effect] += int(row.item_count)
            amounts[row.result_effect] += Decimal(row.amount)
        expense = FinancialResultEffect.EXPENSE.value
        income = FinancialResultEffect.INCOME.value
        return FinancialBudgetRealization(
            rows=rows,
            unclassified_expense=FinancialBudgetCoverageSlice(
                counts[expense], amounts[expense]
            ),
            unclassified_income=FinancialBudgetCoverageSlice(
                counts[income], amounts[income]
            ),
        )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        raise FinancialBudgetPersistenceError("budget state is invalid") from None


def _date_column(
    budget: FinancialBudgetRecord, movements: FromClause
) -> ColumnElement[Any]:
    """The Movement date that places an amount in the month (the budget's basis)."""
    if budget.date_basis is FinancialBudgetDateBasis.CASH:
        return movements.c.effective_date
    return movements.c.competence_date


def _audience_filter(
    budget: FinancialBudgetRecord, accounts: FromClause
) -> list[ColumnElement[bool]]:
    """Pin the account audience to the budget scope.

    A HOUSEHOLD budget only ever sums HOUSEHOLD accounts, so every member reads
    identical numbers and nobody's PERSONAL spending leaks into a shared figure.
    A PERSONAL budget only sums the owner's PERSONAL accounts. SHARED accounts are
    out of the v1 budget scope.
    """
    conditions = [accounts.c.visibility_scope == budget.visibility_scope.value]
    if budget.visibility_scope is FinancialVisibilityScope.PERSONAL:
        conditions.append(accounts.c.owner_operator_id == budget.owner_operator_id)
    return conditions


def _realized_statement(
    budget: FinancialBudgetRecord,
    installation_id: UUID,
    window: tuple[date, date],
) -> Select[Any]:
    movements = financial_movements
    accounts = financial_accounts
    sets = financial_movement_allocation_sets
    allocations = financial_movement_allocations
    lines = financial_budget_lines
    successor = sets.alias("successor")
    # A REVERSAL is classified through the Movement it reverses (its own allocation
    # set never exists); a STANDARD Movement through its own.
    classified_movement_id = func.coalesce(movements.c.reversal_of_id, movements.c.id)
    signed = case(
        (movements.c.role == _STANDARD, func.abs(allocations.c.amount)),
        else_=-func.abs(allocations.c.amount),
    )
    date_column = _date_column(budget, movements)
    return (
        select(
            allocations.c.category_id,
            movements.c.result_effect,
            func.sum(signed).label("amount"),
        )
        .select_from(
            movements.join(
                accounts,
                (accounts.c.id == movements.c.account_id)
                & (accounts.c.installation_id == movements.c.installation_id)
                & (accounts.c.residence_id == movements.c.residence_id),
            )
            .join(
                sets,
                (sets.c.movement_id == classified_movement_id)
                & (sets.c.installation_id == movements.c.installation_id)
                & (sets.c.residence_id == movements.c.residence_id)
                & ~exists(
                    select(successor.c.id).where(successor.c.supersedes_id == sets.c.id)
                ),
            )
            .join(allocations, allocations.c.allocation_set_id == sets.c.id)
            .join(
                lines,
                (lines.c.budget_id == budget.id)
                & (lines.c.revision == budget.version)
                & (lines.c.category_id == allocations.c.category_id)
                & (lines.c.result_effect == movements.c.result_effect),
            )
        )
        .where(
            movements.c.installation_id == installation_id,
            movements.c.residence_id == budget.residence_id,
            movements.c.currency == budget.currency,
            movements.c.result_effect.in_(_EFFECTS),
            date_column >= window[0],
            date_column < window[1],
            *_audience_filter(budget, accounts),
        )
        .group_by(allocations.c.category_id, movements.c.result_effect)
    )


def _coverage_statement(
    budget: FinancialBudgetRecord,
    installation_id: UUID,
    window: tuple[date, date],
) -> Select[Any]:
    """Unclassified INCOME/EXPENSE impact in the window, outside every line.

    ``+|amount|`` for an unclassified STANDARD Movement that is not reversed
    inside the window; ``-|amount|`` for a REVERSAL, inside the window, of an
    unclassified original that lies outside it. A STANDARD/REVERSAL pair that both
    fall inside the window cancels out entirely (count and amount).
    """
    movements = financial_movements
    reversal = financial_movements.alias("reversal")
    original = financial_movements.alias("original")
    accounts = financial_accounts
    sets = financial_movement_allocation_sets

    def _has_set(movement_id: ColumnElement[Any]) -> Exists:
        return exists(select(sets.c.id).where(sets.c.movement_id == movement_id))

    standard_date = _date_column(budget, movements)
    reversal_date = _date_column(budget, reversal)
    original_date = _date_column(budget, original)

    standard_part = (
        select(
            movements.c.result_effect,
            func.count().label("item_count"),
            func.coalesce(func.sum(func.abs(movements.c.amount)), 0).label("amount"),
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
            movements.c.residence_id == budget.residence_id,
            movements.c.role == _STANDARD,
            movements.c.currency == budget.currency,
            movements.c.result_effect.in_(_EFFECTS),
            standard_date >= window[0],
            standard_date < window[1],
            ~_has_set(movements.c.id),
            ~exists(
                select(reversal.c.id).where(
                    reversal.c.reversal_of_id == movements.c.id,
                    reversal_date >= window[0],
                    reversal_date < window[1],
                )
            ),
            *_audience_filter(budget, accounts),
        )
        .group_by(movements.c.result_effect)
    )

    reversal_part = (
        select(
            reversal.c.result_effect,
            func.count().label("item_count"),
            func.coalesce(-func.sum(func.abs(reversal.c.amount)), 0).label("amount"),
        )
        .select_from(
            reversal.join(original, original.c.id == reversal.c.reversal_of_id).join(
                accounts,
                (accounts.c.id == reversal.c.account_id)
                & (accounts.c.installation_id == reversal.c.installation_id)
                & (accounts.c.residence_id == reversal.c.residence_id),
            )
        )
        .where(
            reversal.c.installation_id == installation_id,
            reversal.c.residence_id == budget.residence_id,
            reversal.c.role == _REVERSAL,
            reversal.c.currency == budget.currency,
            reversal.c.result_effect.in_(_EFFECTS),
            reversal_date >= window[0],
            reversal_date < window[1],
            ~_has_set(original.c.id),
            (original_date < window[0]) | (original_date >= window[1]),
            *_audience_filter(budget, accounts),
        )
        .group_by(reversal.c.result_effect)
    )
    combined = union_all(standard_part, reversal_part).subquery("coverage")
    return select(combined.c.result_effect, combined.c.item_count, combined.c.amount)


__all__ = ["FinancialBudgetRealizationStore"]
