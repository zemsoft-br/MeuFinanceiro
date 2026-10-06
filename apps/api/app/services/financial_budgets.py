"""Application orchestration of monthly category budgets.

Budgets are planning. This service never touches the ledger or classification: the
plan comes from the budget store, the realized amounts and coverage come from the
read-only realization store (derived from the ledger and the current allocation
set on every read), and the per-line arithmetic (remaining, status, percent) is the
pure domain function ``summarize_budget``. The API and Flutter hold no financial
rule of their own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable
from uuid import UUID

from meufinanceiro_finance import (
    FinancialBudgetDraft,
    FinancialBudgetRealization,
    FinancialBudgetRecord,
    FinancialBudgetReplacement,
    FinancialBudgetSummary,
    can_edit_budget,
    parse_budget_period,
    summarize_budget,
)


class BudgetRequestError(ValueError):
    """The request cannot be served: bad period or malformed intent."""


@runtime_checkable
class BudgetStoreBoundary(Protocol):
    def create_budget(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialBudgetDraft,
    ) -> FinancialBudgetRecord: ...

    def get_budget(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        budget_id: UUID,
    ) -> FinancialBudgetRecord: ...

    def list_budgets(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        period_start: date,
    ) -> tuple[FinancialBudgetRecord, ...]: ...

    def replace_budget(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        budget_id: UUID,
        replacement: FinancialBudgetReplacement,
    ) -> FinancialBudgetRecord: ...


@runtime_checkable
class BudgetRealizationBoundary(Protocol):
    def read_realization(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        budget_id: UUID,
    ) -> tuple[FinancialBudgetRecord, FinancialBudgetRealization]: ...


@dataclass(frozen=True, slots=True, repr=False)
class BudgetView:
    """A budget plus what the current operator may do with it (server-decided)."""

    budget: FinancialBudgetRecord
    can_edit: bool

    def __repr__(self) -> str:
        return f"BudgetView(can_edit={self.can_edit})"


@dataclass(frozen=True, slots=True, repr=False)
class BudgetSummaryView:
    summary: FinancialBudgetSummary
    can_edit: bool

    def __repr__(self) -> str:
        return f"BudgetSummaryView(can_edit={self.can_edit})"


class FinancialBudgetService:
    """List, create, read, CAS-edit and summarize monthly budgets."""

    def __init__(
        self,
        budget_store: BudgetStoreBoundary,
        realization_store: BudgetRealizationBoundary,
    ) -> None:
        if not isinstance(budget_store, BudgetStoreBoundary):
            raise TypeError("budget_store must satisfy BudgetStoreBoundary")
        if not isinstance(realization_store, BudgetRealizationBoundary):
            raise TypeError("realization_store must satisfy BudgetRealizationBoundary")
        self._budgets = budget_store
        self._realization = realization_store

    def list_budgets(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        period: str,
    ) -> tuple[BudgetView, ...]:
        try:
            period_start = parse_budget_period(period)
        except (TypeError, ValueError):
            raise BudgetRequestError("invalid budget period") from None
        records = self._budgets.list_budgets(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            period_start=period_start,
        )
        return tuple(_view(record, operator_id) for record in records)

    def create_budget(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialBudgetDraft,
    ) -> BudgetView:
        record = self._budgets.create_budget(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=idempotency_key,
            draft=draft,
        )
        return _view(record, operator_id)

    def get_budget(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        budget_id: UUID,
    ) -> BudgetView:
        record = self._budgets.get_budget(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            budget_id=budget_id,
        )
        return _view(record, operator_id)

    def replace_budget(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        budget_id: UUID,
        replacement: FinancialBudgetReplacement,
    ) -> BudgetView:
        record = self._budgets.replace_budget(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            budget_id=budget_id,
            replacement=replacement,
        )
        return _view(record, operator_id)

    def summary(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        budget_id: UUID,
    ) -> BudgetSummaryView:
        """Planned vs realized from one consistent snapshot. Never cached."""
        record, realization = self._realization.read_realization(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            budget_id=budget_id,
        )
        return BudgetSummaryView(
            summary=summarize_budget(record, realization),
            can_edit=can_edit_budget(budget=record, operator_id=operator_id),
        )


def _view(record: FinancialBudgetRecord, operator_id: UUID) -> BudgetView:
    return BudgetView(
        budget=record, can_edit=can_edit_budget(budget=record, operator_id=operator_id)
    )


__all__ = [
    "BudgetRealizationBoundary",
    "BudgetRequestError",
    "BudgetStoreBoundary",
    "BudgetSummaryView",
    "BudgetView",
    "FinancialBudgetService",
]
