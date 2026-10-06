from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    FinancialBudgetCoverageSlice,
    FinancialBudgetDateBasis,
    FinancialBudgetLineRecord,
    FinancialBudgetLineStatus,
    FinancialBudgetPeriodKind,
    FinancialBudgetRealization,
    FinancialBudgetRealizedRow,
    FinancialBudgetRecord,
    FinancialResultEffect,
    FinancialVisibilityScope,
    Money,
)

from app.services.financial_budgets import (
    BudgetRequestError,
    FinancialBudgetService,
)

_NOW = datetime(2026, 10, 5, tzinfo=UTC)
_OWNER = uuid4()
_MARKET = uuid4()


def _record(owner: UUID = _OWNER) -> FinancialBudgetRecord:
    return FinancialBudgetRecord(
        id=uuid4(),
        residence_id=uuid4(),
        owner_operator_id=owner,
        visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
        name="Outubro",
        currency="BRL",
        period_kind=FinancialBudgetPeriodKind.MONTHLY,
        period_start=date(2026, 10, 1),
        date_basis=FinancialBudgetDateBasis.CASH,
        version=1,
        created_at=_NOW,
        updated_at=_NOW,
        lines=(
            FinancialBudgetLineRecord(
                _MARKET, FinancialResultEffect.EXPENSE, Money(Decimal("100"), "BRL")
            ),
        ),
    )


class _Budgets:
    def __init__(self, record: FinancialBudgetRecord) -> None:
        self.record = record
        self.periods: list[date] = []

    def create_budget(self, **kwargs: object) -> FinancialBudgetRecord:
        return self.record

    def get_budget(self, **kwargs: object) -> FinancialBudgetRecord:
        return self.record

    def list_budgets(self, **kwargs: object) -> tuple[FinancialBudgetRecord, ...]:
        self.periods.append(kwargs["period_start"])  # type: ignore[arg-type]
        return (self.record,)

    def replace_budget(self, **kwargs: object) -> FinancialBudgetRecord:
        return self.record


class _Realization:
    def __init__(self, record: FinancialBudgetRecord, amount: str) -> None:
        self.record = record
        self.amount = Decimal(amount)
        self.calls = 0

    def read_realization(
        self, **kwargs: object
    ) -> tuple[FinancialBudgetRecord, FinancialBudgetRealization]:
        self.calls += 1
        return self.record, FinancialBudgetRealization(
            rows=(
                FinancialBudgetRealizedRow(
                    _MARKET, FinancialResultEffect.EXPENSE, self.amount
                ),
            ),
            unclassified_expense=FinancialBudgetCoverageSlice(2, Decimal("7.5")),
            unclassified_income=FinancialBudgetCoverageSlice(0, Decimal(0)),
        )


def _scope(operator: UUID = _OWNER) -> dict[str, UUID]:
    return {
        "installation_id": uuid4(),
        "residence_id": uuid4(),
        "operator_id": operator,
    }


def test_service_requires_the_boundaries() -> None:
    record = _record()
    with pytest.raises(TypeError):
        FinancialBudgetService(object(), _Realization(record, "1"))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        FinancialBudgetService(_Budgets(record), object())  # type: ignore[arg-type]


def test_summary_is_computed_by_the_domain_and_never_cached() -> None:
    record = _record()
    realization = _Realization(record, "130")
    service = FinancialBudgetService(_Budgets(record), realization)
    first = service.summary(**_scope(), budget_id=record.id)
    service.summary(**_scope(), budget_id=record.id)
    assert realization.calls == 2  # one derivation per read, no memoization
    line = first.summary.lines[0]
    assert line.status is FinancialBudgetLineStatus.OVER
    assert line.remaining == Money(Decimal("-30"), "BRL")
    assert first.summary.coverage.unclassified_expense_count == 2
    assert first.summary.coverage.unclassified_expense == Money(Decimal("7.5"), "BRL")
    assert first.can_edit is True


def test_edit_authority_is_the_owners_alone() -> None:
    record = _record()
    service = FinancialBudgetService(_Budgets(record), _Realization(record, "0"))
    assert service.get_budget(**_scope(), budget_id=record.id).can_edit is True
    other = _scope(uuid4())
    assert service.get_budget(**other, budget_id=record.id).can_edit is False
    assert service.summary(**other, budget_id=record.id).can_edit is False


def test_list_parses_the_period_strictly() -> None:
    record = _record()
    budgets = _Budgets(record)
    service = FinancialBudgetService(budgets, _Realization(record, "0"))
    views = service.list_budgets(**_scope(), period="2026-10")
    assert [view.budget.id for view in views] == [record.id]
    assert budgets.periods == [date(2026, 10, 1)]
    for bad in ("2026-13", "2026-10-01", "x", ""):
        with pytest.raises(BudgetRequestError):
            service.list_budgets(**_scope(), period=bad)
