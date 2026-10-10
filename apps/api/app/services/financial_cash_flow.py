"""Application orchestration of the read-only cash flow (ADR-0031).

The window is validated against the injected clock, the source is read from one
consistent snapshot by the store, and the projection is the pure domain function
``project_cash_flow``. Nothing here writes, generates occurrences or computes a
financial rule of its own; the API and Flutter only serialize the result.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from meufinanceiro_finance import (
    FinancialCashFlowLimitError,
    FinancialCashFlowProjection,
    FinancialCashFlowSource,
    FinancialCashFlowWindow,
    FinancialCashFlowWindowError,
    FinancialLedgerStateError,
    cash_flow_window,
    project_cash_flow,
)
from meufinanceiro_persistence.financial_cash_flow_store import (
    FinancialCashFlowLimitExceededError,
    FinancialCashFlowPersistenceError,
)


class CashFlowRequestError(ValueError):
    """The window is outside the v1 contract."""


@runtime_checkable
class CashFlowSourceBoundary(Protocol):
    def read_source(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        window: FinancialCashFlowWindow,
        account_ids: tuple[UUID, ...] | None = None,
        currency: str | None = None,
    ) -> FinancialCashFlowSource: ...


class FinancialCashFlowService:
    """Read the cash flow of the operator's residence for one window."""

    def __init__(
        self,
        store: CashFlowSourceBoundary,
        *,
        clock: Callable[[], date],
        instant: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(store, CashFlowSourceBoundary):
            raise TypeError("store must satisfy CashFlowSourceBoundary")
        self._store = store
        self._clock = clock
        self._instant = instant or _utc_now

    def read_cash_flow(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        from_date: date | None,
        through_date: date | None,
        account_ids: tuple[UUID, ...] | None,
        currency: str | None,
    ) -> FinancialCashFlowProjection:
        today = self._clock()
        if isinstance(today, datetime) or not isinstance(today, date):
            raise TypeError("clock must return a date")
        try:
            window = cash_flow_window(
                from_date=from_date, through_date=through_date, reference_date=today
            )
        except FinancialCashFlowWindowError:
            raise CashFlowRequestError("invalid cash flow window") from None
        source = self._store.read_source(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            window=window,
            account_ids=account_ids,
            currency=currency,
        )
        try:
            return project_cash_flow(
                window=window, source=source, calculated_at=self._instant()
            )
        except FinancialCashFlowLimitError:
            raise FinancialCashFlowLimitExceededError(
                "cash flow window has too many events"
            ) from None
        except FinancialLedgerStateError:
            # Canonical resources disagree with each other: never show a guess.
            raise FinancialCashFlowPersistenceError(
                "cash flow state is invalid"
            ) from None


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = ["CashFlowRequestError", "CashFlowSourceBoundary", "FinancialCashFlowService"]
