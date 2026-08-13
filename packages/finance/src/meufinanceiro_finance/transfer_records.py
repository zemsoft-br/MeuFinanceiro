"""Immutable persisted transfer relation contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from meufinanceiro_finance.ids import validate_financial_resource_id
from meufinanceiro_finance.money import validate_currency_code
from meufinanceiro_finance.transfers import FinancialTransferRole


@dataclass(frozen=True, slots=True, repr=False)
class FinancialTransferRecord:
    """One append-only relation linking exactly two canonical Movement legs."""

    id: UUID
    source_account_id: UUID
    destination_account_id: UUID
    currency: str
    source_movement_id: UUID
    destination_movement_id: UUID
    role: FinancialTransferRole
    reversal_of_id: UUID | None
    created_by_operator_id: UUID
    created_at: datetime

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.id)
        validate_financial_resource_id(self.source_account_id)
        validate_financial_resource_id(self.destination_account_id)
        if self.source_account_id == self.destination_account_id:
            raise ValueError("transfer accounts must be distinct")
        object.__setattr__(self, "currency", validate_currency_code(self.currency))
        validate_financial_resource_id(self.source_movement_id)
        validate_financial_resource_id(self.destination_movement_id)
        if self.source_movement_id == self.destination_movement_id:
            raise ValueError("transfer Movement legs must be distinct")
        if not isinstance(self.role, FinancialTransferRole):
            raise TypeError("role must be FinancialTransferRole")
        if self.role is FinancialTransferRole.STANDARD:
            if self.reversal_of_id is not None:
                raise ValueError("STANDARD transfer must not reference another transfer")
        else:
            if self.reversal_of_id is None:
                raise ValueError("REVERSAL transfer requires reversal_of_id")
            validate_financial_resource_id(self.reversal_of_id)
        _require_uuid(self.created_by_operator_id, "created_by_operator_id")
        _require_aware(self.created_at, "created_at")

    def __repr__(self) -> str:
        return (
            "FinancialTransferRecord("
            f"role={self.role.value!r}, currency={self.currency!r}, "
            "<accounts-movements-identities-redacted>)"
        )


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


__all__ = ["FinancialTransferRecord"]
