"""Canonical provider-neutral contracts for atomic internal transfers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from meufinanceiro_finance.ids import validate_financial_resource_id
from meufinanceiro_finance.money import Money
from meufinanceiro_finance.movements import (
    FinancialMovementDraft,
    FinancialResultEffect,
)

_TRANSFER_TEXT_MAX_LENGTH = 256


class FinancialTransferRole(StrEnum):
    """Immutable role of one persisted transfer operation."""

    STANDARD = "STANDARD"
    REVERSAL = "REVERSAL"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialTransferDraft:
    """Positive-magnitude intent for one same-currency internal transfer."""

    source_account_id: UUID
    destination_account_id: UUID
    magnitude: Money
    effective_date: date
    competence_date: date
    description: str

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.source_account_id)
        validate_financial_resource_id(self.destination_account_id)
        if self.source_account_id == self.destination_account_id:
            raise ValueError("transfer accounts must be distinct")
        if not isinstance(self.magnitude, Money):
            raise TypeError("magnitude must be Money")
        if self.magnitude.amount <= 0:
            raise ValueError("transfer magnitude must be positive")

        source, _destination = self.to_movement_drafts()
        object.__setattr__(self, "description", source.description)

    def to_movement_drafts(
        self,
    ) -> tuple[FinancialMovementDraft, FinancialMovementDraft]:
        """Return source then destination canonical NEUTRAL Movement drafts."""
        source = FinancialMovementDraft(
            account_id=self.source_account_id,
            amount=-self.magnitude,
            result_effect=FinancialResultEffect.NEUTRAL,
            effective_date=self.effective_date,
            competence_date=self.competence_date,
            description=self.description,
        )
        destination = FinancialMovementDraft(
            account_id=self.destination_account_id,
            amount=self.magnitude,
            result_effect=FinancialResultEffect.NEUTRAL,
            effective_date=self.effective_date,
            competence_date=self.competence_date,
            description=self.description,
        )
        return source, destination

    def __repr__(self) -> str:
        return (
            "FinancialTransferDraft("
            f"currency={self.magnitude.currency!r}, "
            "<magnitude-accounts-dates-description-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialTransferReversalDraft:
    """Intent to reverse both legs of one original transfer atomically."""

    transfer_id: UUID
    effective_date: date
    competence_date: date
    reason: str

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.transfer_id)
        _require_plain_date(self.effective_date, "effective_date")
        _require_plain_date(self.competence_date, "competence_date")
        object.__setattr__(
            self,
            "reason",
            _clean_text(self.reason, "reason"),
        )

    def __repr__(self) -> str:
        return "FinancialTransferReversalDraft(<transfer-dates-reason-redacted>)"


def _require_plain_date(value: date, field_name: str) -> None:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError(f"{field_name} must be date")


def _clean_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if len(normalized) > _TRANSFER_TEXT_MAX_LENGTH:
        raise ValueError(f"{field_name} exceeds {_TRANSFER_TEXT_MAX_LENGTH} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ValueError(f"{field_name} contains control characters")
    return normalized


__all__ = [
    "FinancialTransferDraft",
    "FinancialTransferReversalDraft",
    "FinancialTransferRole",
]
