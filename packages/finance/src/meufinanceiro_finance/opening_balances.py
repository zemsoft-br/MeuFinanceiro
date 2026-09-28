"""Immutable opening-balance anchor contracts for financial accounts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from meufinanceiro_finance.ids import validate_financial_resource_id
from meufinanceiro_finance.money import Money


@dataclass(frozen=True, slots=True, repr=False)
class FinancialOpeningBalanceDraft:
    """One immutable account opening anchor before persistence scope assignment."""

    amount: Money
    effective_date: date

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Money):
            raise TypeError("amount must be Money")
        _require_date(self.effective_date, "effective_date")

    def __repr__(self) -> str:
        return (
            "FinancialOpeningBalanceDraft("
            f"currency={self.amount.currency!r}, effective_date={self.effective_date!r}, "
            "amount=<redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialOpeningBalanceRecord:
    """Persisted immutable opening anchor for one canonical financial account."""

    id: UUID
    residence_id: UUID
    account_id: UUID
    amount: Money
    effective_date: date
    created_by_operator_id: UUID
    created_at: datetime

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.id)
        _require_uuid(self.residence_id, "residence_id")
        validate_financial_resource_id(self.account_id)
        if not isinstance(self.amount, Money):
            raise TypeError("amount must be Money")
        _require_date(self.effective_date, "effective_date")
        _require_uuid(self.created_by_operator_id, "created_by_operator_id")
        _require_aware(self.created_at, "created_at")

    def __repr__(self) -> str:
        return (
            "FinancialOpeningBalanceRecord("
            f"currency={self.amount.currency!r}, effective_date={self.effective_date!r}, "
            "amount=<redacted>, <identity-and-actor-redacted>)"
        )


def _require_date(value: date, field_name: str) -> None:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError(f"{field_name} must be date")


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


def _require_aware(value: datetime, field_name: str) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{field_name} must be timezone-aware")


__all__ = [
    "FinancialOpeningBalanceDraft",
    "FinancialOpeningBalanceRecord",
]
