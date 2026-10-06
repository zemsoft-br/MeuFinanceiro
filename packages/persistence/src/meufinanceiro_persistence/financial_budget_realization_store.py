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

Cost shape: explicit SQL with materialized steps. (1) the Movements of the month
(visible, audience-pinned); (2) one scan of the shares of exactly those Movements
via movement_id = ANY(ARRAY(...)). Under forced RLS every row read from
movement_allocations pays the policy chain and a nested-loop plan re-evaluates it
on each rescan (measured ~1.3 s for a 1.9k Movement month against ~45 ms without
RLS); one array-keyed scan pays it once per share.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
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
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.financial_budget_store import (
    FinancialBudgetAccessError,
    FinancialBudgetNotFoundError,
    FinancialBudgetPersistenceError,
    _load_records,
    _prepare,
    _require_scope,
    _visible_row,
)
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementAccessError,
)

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
    params = _params(budget, installation_id, window)
    realized = connection.execute(text(_realized_sql(budget)), params).all()
    coverage = connection.execute(text(_coverage_sql(budget)), params).all()
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


def _params(
    budget: FinancialBudgetRecord, installation_id: UUID, window: tuple[date, date]
) -> dict[str, object]:
    params: dict[str, object] = {
        "installation_id": installation_id,
        "residence_id": budget.residence_id,
        "currency": budget.currency,
        "window_start": window[0],
        "window_end": window[1],
        "scope": budget.visibility_scope.value,
    }
    if budget.visibility_scope is FinancialVisibilityScope.PERSONAL:
        params["owner_id"] = budget.owner_operator_id
    return params


def _date_column(budget: FinancialBudgetRecord) -> str:
    """The Movement column that places an amount in the month (the budget basis).

    The only value spliced into the SQL, and only ever one of two literals.
    """
    if budget.date_basis is FinancialBudgetDateBasis.CASH:
        return "effective_date"
    return "competence_date"


def _audience_sql(budget: FinancialBudgetRecord) -> str:
    """Pin the account audience to the budget scope.

    A HOUSEHOLD budget only ever sums HOUSEHOLD accounts, so every member reads
    identical numbers and nobody's PERSONAL spending leaks into a shared figure.
    A PERSONAL budget only sums the owner's PERSONAL accounts. SHARED accounts are
    out of the v1 budget scope.
    """
    if budget.visibility_scope is FinancialVisibilityScope.PERSONAL:
        return "a.visibility_scope = :scope AND a.owner_operator_id = :owner_id"
    return "a.visibility_scope = :scope"


def _window_cte(budget: FinancialBudgetRecord) -> str:
    """Step 1: the Movements of the month (RLS-visible, audience-pinned, in currency).

    A REVERSAL is classified through the STANDARD it reverses, so ``classified_id``
    is that Movement's id; a STANDARD is classified through its own.
    """
    column = _date_column(budget)
    return f"""
    win AS MATERIALIZED (
        SELECT m.id, m.role, m.result_effect, m.amount, m.reversal_of_id,
               CASE m.role WHEN 'STANDARD' THEN m.id ELSE m.reversal_of_id END
                   AS classified_id
          FROM finance.movements m
          JOIN finance.accounts a
            ON a.id = m.account_id
           AND a.installation_id = m.installation_id
           AND a.residence_id = m.residence_id
         WHERE m.installation_id = :installation_id
           AND m.residence_id = :residence_id
           AND m.currency = :currency
           AND m.result_effect IN ('INCOME', 'EXPENSE')
           AND m.{column} >= :window_start
           AND m.{column} < :window_end
           AND {_audience_sql(budget)}
    )"""


def _realized_sql(budget: FinancialBudgetRecord) -> str:
    """Realized per (category, effect): ``+|share|`` STANDARD, ``-|share|`` REVERSAL.

    One row per distinct (category, effect) with activity in the month, so the
    result is small whatever the number of Movements; pairing with the budget
    lines happens in the pure domain function.
    """
    return f"""
    /* budget-realized */
    WITH {_window_cte(budget)},
    shares AS MATERIALIZED (
        SELECT al.allocation_set_id, al.movement_id, al.category_id,
               abs(al.amount) AS magnitude
          FROM finance.movement_allocations al
         WHERE al.installation_id = :installation_id
           AND al.residence_id = :residence_id
           AND al.movement_id = ANY (ARRAY(SELECT classified_id FROM win))
    )
    SELECT s.category_id, w.result_effect,
           sum(CASE WHEN w.role = 'STANDARD' THEN s.magnitude
                    ELSE -s.magnitude END) AS amount
      FROM win w
      JOIN shares s ON s.movement_id = w.classified_id
     WHERE NOT EXISTS (
               SELECT 1 FROM finance.movement_allocation_sets succ
                WHERE succ.supersedes_id = s.allocation_set_id)
     GROUP BY s.category_id, w.result_effect
    """


def _coverage_sql(budget: FinancialBudgetRecord) -> str:
    """Unclassified INCOME/EXPENSE impact in the window, outside every line.

    ``+|amount|`` for an unclassified STANDARD Movement that is not reversed
    inside the window; ``-|amount|`` for a REVERSAL, inside the window, of an
    unclassified original that lies outside it. A STANDARD/REVERSAL pair that both
    fall inside the window cancels out entirely (count and amount).
    """
    return f"""
    /* budget-coverage */
    WITH {_window_cte(budget)},
    classified AS MATERIALIZED (
        SELECT DISTINCT st.movement_id
          FROM finance.movement_allocation_sets st
         WHERE st.installation_id = :installation_id
           AND st.residence_id = :residence_id
           AND st.movement_id = ANY (ARRAY(SELECT classified_id FROM win))
    )
    SELECT x.result_effect, count(*) AS item_count, sum(x.signed) AS amount
      FROM (
            SELECT w.result_effect, abs(w.amount) AS signed
              FROM win w
             WHERE w.role = 'STANDARD'
               AND NOT EXISTS (
                       SELECT 1 FROM classified c WHERE c.movement_id = w.id)
               AND NOT EXISTS (
                       SELECT 1 FROM win r
                        WHERE r.role = 'REVERSAL' AND r.reversal_of_id = w.id)
            UNION ALL
            SELECT w.result_effect, -abs(w.amount)
              FROM win w
             WHERE w.role = 'REVERSAL'
               AND NOT EXISTS (
                       SELECT 1 FROM classified c
                        WHERE c.movement_id = w.reversal_of_id)
               AND NOT EXISTS (
                       SELECT 1 FROM win o
                        WHERE o.role = 'STANDARD' AND o.id = w.reversal_of_id)
           ) x
     GROUP BY x.result_effect
    """


__all__ = ["FinancialBudgetRealizationStore"]
