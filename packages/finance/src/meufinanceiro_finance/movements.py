"""Canonical append-only Movement contracts for the financial ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from meufinanceiro_finance.ids import validate_financial_resource_id
from meufinanceiro_finance.money import Money

_DESCRIPTION_MAX_LENGTH = 256
_REVERSAL_REASON_MAX_LENGTH = 256


class FinancialResultEffect(StrEnum):
    """How one canonical Movement contributes to economic result."""

    INCOME = "INCOME"
    EXPENSE = "EXPENSE"
    NEUTRAL = "NEUTRAL"


class FinancialMovementRole(StrEnum):
    """Immutable role of one ledger event."""

    STANDARD = "STANDARD"
    REVERSAL = "REVERSAL"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialMovementDraft:
    """Intent for one original effective account Movement."""

    account_id: UUID
    amount: Money
    result_effect: FinancialResultEffect
    effective_date: date
    competence_date: date
    description: str

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.account_id)
        if not isinstance(self.amount, Money):
            raise TypeError("amount must be Money")
        if not isinstance(self.result_effect, FinancialResultEffect):
            raise TypeError("result_effect must be FinancialResultEffect")
        _require_plain_date(self.effective_date, "effective_date")
        _require_plain_date(self.competence_date, "competence_date")
        object.__setattr__(
            self,
            "description",
            _clean_text(
                self.description,
                "description",
                _DESCRIPTION_MAX_LENGTH,
            ),
        )
        _validate_standard_amount(self.amount, self.result_effect)

    def __repr__(self) -> str:
        return (
            "FinancialMovementDraft("
            f"result_effect={self.result_effect.value!r}, "
            f"currency={self.amount.currency!r}, "
            "<amount-account-dates-description-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialMovementReversalDraft:
    """Intent to fully reverse one original Movement without caller-supplied amount."""

    movement_id: UUID
    effective_date: date
    competence_date: date
    reason: str

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.movement_id)
        _require_plain_date(self.effective_date, "effective_date")
        _require_plain_date(self.competence_date, "competence_date")
        object.__setattr__(
            self,
            "reason",
            _clean_text(self.reason, "reason", _REVERSAL_REASON_MAX_LENGTH),
        )

    def __repr__(self) -> str:
        return (
            "FinancialMovementReversalDraft("
            "<movement-dates-reason-redacted>)"
        )


def _validate_standard_amount(
    amount: Money,
    result_effect: FinancialResultEffect,
) -> None:
    if amount.amount == 0:
        raise ValueError("Movement amount must not be zero")
    if result_effect is FinancialResultEffect.INCOME and amount.amount <= 0:
        raise ValueError("INCOME Movement amount must be positive")
    if result_effect is FinancialResultEffect.EXPENSE and amount.amount >= 0:
        raise ValueError("EXPENSE Movement amount must be negative")


def _require_plain_date(value: date, field_name: str) -> None:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError(f"{field_name} must be date")


def _clean_text(value: str, field_name: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} exceeds {max_length} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ValueError(f"{field_name} contains control characters")
    return normalized


__all__ = [
    "FinancialMovementDraft",
    "FinancialMovementReversalDraft",
    "FinancialMovementRole",
    "FinancialResultEffect",
]
