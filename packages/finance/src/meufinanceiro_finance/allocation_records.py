"""Persisted immutable records for Movement classification and allocation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from meufinanceiro_finance.allocations import (
    FinancialMovementAllocationDraft,
    FinancialMovementAllocationSetDraft,
)
from meufinanceiro_finance.ids import validate_financial_resource_id
from meufinanceiro_finance.money import Money


@dataclass(frozen=True, slots=True, repr=False)
class FinancialMovementAllocationRecord:
    """One persisted analytical share inside an immutable allocation set."""

    id: UUID
    allocation_set_id: UUID
    category_id: UUID
    amount: Money
    created_at: datetime

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.id)
        validate_financial_resource_id(self.allocation_set_id)
        validate_financial_resource_id(self.category_id)
        if not isinstance(self.amount, Money):
            raise TypeError("amount must be Money")
        if self.amount.amount == 0:
            raise ValueError("allocation amount must not be zero")
        _require_aware(self.created_at, "created_at")

    def to_draft(self) -> FinancialMovementAllocationDraft:
        return FinancialMovementAllocationDraft(
            category_id=self.category_id,
            amount=self.amount,
        )

    def __repr__(self) -> str:
        return (
            "FinancialMovementAllocationRecord("
            f"currency={self.amount.currency!r}, <identity-and-amount-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialMovementAllocationSetRecord:
    """One immutable version of a Movement's analytical classification."""

    id: UUID
    movement_id: UUID
    revision: int
    supersedes_id: UUID | None
    created_by_operator_id: UUID
    created_at: datetime
    allocations: tuple[FinancialMovementAllocationRecord, ...]

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.id)
        validate_financial_resource_id(self.movement_id)
        if isinstance(self.revision, bool) or not isinstance(self.revision, int):
            raise TypeError("revision must be an integer")
        if self.revision < 1:
            raise ValueError("revision must be positive")
        if self.supersedes_id is not None:
            validate_financial_resource_id(self.supersedes_id)
        if self.revision == 1 and self.supersedes_id is not None:
            raise ValueError("first revision must not supersede another set")
        if self.revision > 1 and self.supersedes_id is None:
            raise ValueError("later revision must supersede another set")
        _require_uuid(self.created_by_operator_id, "created_by_operator_id")
        _require_aware(self.created_at, "created_at")
        if not isinstance(self.allocations, tuple):
            raise TypeError("allocations must be a tuple")
        if not self.allocations:
            raise ValueError("allocation set must contain allocations")
        if not all(
            isinstance(item, FinancialMovementAllocationRecord)
            for item in self.allocations
        ):
            raise TypeError(
                "allocations must contain FinancialMovementAllocationRecord"
            )
        if any(item.allocation_set_id != self.id for item in self.allocations):
            raise ValueError("allocation belongs to another set")

        FinancialMovementAllocationSetDraft(
            movement_id=self.movement_id,
            allocations=tuple(item.to_draft() for item in self.allocations),
        )

    def __repr__(self) -> str:
        return (
            "FinancialMovementAllocationSetRecord("
            f"revision={self.revision}, allocation_count={len(self.allocations)}, "
            "<identity-and-amounts-redacted>)"
        )


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


__all__ = [
    "FinancialMovementAllocationRecord",
    "FinancialMovementAllocationSetRecord",
]
