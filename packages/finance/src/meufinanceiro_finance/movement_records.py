"""Immutable persisted Movement record contract for ledger reads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from meufinanceiro_finance.ids import validate_financial_resource_id
from meufinanceiro_finance.money import Money
from meufinanceiro_finance.movements import (
    FinancialMovementRole,
    FinancialResultEffect,
)

_TEXT_MAX_LENGTH = 256


@dataclass(frozen=True, slots=True, repr=False)
class FinancialMovementRecord:
    """One immutable persisted ledger event."""

    id: UUID
    account_id: UUID
    amount: Money
    result_effect: FinancialResultEffect
    role: FinancialMovementRole
    effective_date: date
    competence_date: date
    description: str | None
    reversal_of_id: UUID | None
    reversal_reason: str | None
    created_by_operator_id: UUID
    created_at: datetime

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.id)
        validate_financial_resource_id(self.account_id)
        if not isinstance(self.amount, Money):
            raise TypeError("amount must be Money")
        if self.amount.amount == 0:
            raise ValueError("Movement amount must not be zero")
        if not isinstance(self.result_effect, FinancialResultEffect):
            raise TypeError("result_effect must be FinancialResultEffect")
        if not isinstance(self.role, FinancialMovementRole):
            raise TypeError("role must be FinancialMovementRole")
        _require_plain_date(self.effective_date, "effective_date")
        _require_plain_date(self.competence_date, "competence_date")
        _require_uuid(self.created_by_operator_id, "created_by_operator_id")
        _require_aware(self.created_at, "created_at")

        if self.role is FinancialMovementRole.STANDARD:
            if self.description is None:
                raise ValueError("STANDARD Movement requires description")
            object.__setattr__(
                self,
                "description",
                _clean_text(self.description, "description"),
            )
            if self.reversal_of_id is not None or self.reversal_reason is not None:
                raise ValueError("STANDARD Movement must not have reversal fields")
            _validate_standard_sign(self.amount, self.result_effect)
            return

        if self.description is not None:
            raise ValueError("REVERSAL Movement must not have description")
        if self.reversal_of_id is None:
            raise ValueError("REVERSAL Movement requires reversal_of_id")
        validate_financial_resource_id(self.reversal_of_id)
        if self.reversal_reason is None:
            raise ValueError("REVERSAL Movement requires reversal_reason")
        object.__setattr__(
            self,
            "reversal_reason",
            _clean_text(self.reversal_reason, "reversal_reason"),
        )

    def __repr__(self) -> str:
        return (
            "FinancialMovementRecord("
            f"role={self.role.value!r}, result_effect={self.result_effect.value!r}, "
            f"currency={self.amount.currency!r}, "
            "<amount-account-dates-description-identities-redacted>)"
        )


def _validate_standard_sign(
    amount: Money,
    result_effect: FinancialResultEffect,
) -> None:
    if result_effect is FinancialResultEffect.INCOME and amount.amount <= 0:
        raise ValueError("INCOME STANDARD Movement amount must be positive")
    if result_effect is FinancialResultEffect.EXPENSE and amount.amount >= 0:
        raise ValueError("EXPENSE STANDARD Movement amount must be negative")


def _clean_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if len(normalized) > _TEXT_MAX_LENGTH:
        raise ValueError(f"{field_name} exceeds {_TEXT_MAX_LENGTH} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ValueError(f"{field_name} contains control characters")
    return normalized


def _require_plain_date(value: date, field_name: str) -> None:
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


__all__ = ["FinancialMovementRecord"]
