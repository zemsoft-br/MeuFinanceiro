"""Provider-neutral contracts for append-only Movement classification and allocation."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from meufinanceiro_finance.access import FinancialVisibilityScope
from meufinanceiro_finance.ids import validate_financial_resource_id
from meufinanceiro_finance.money import Money


@dataclass(frozen=True, slots=True, repr=False)
class FinancialMovementAllocationDraft:
    """One non-zero category share of a canonical Movement."""

    category_id: UUID
    amount: Money

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.category_id)
        if not isinstance(self.amount, Money):
            raise TypeError("amount must be Money")
        if self.amount.amount == 0:
            raise ValueError("allocation amount must not be zero")

    def canonical_material(self) -> tuple[str, str, str]:
        """Return stable category/currency/amount material for request digests."""
        return (
            str(self.category_id),
            self.amount.currency,
            self.amount.canonical_amount,
        )

    def __repr__(self) -> str:
        return (
            "FinancialMovementAllocationDraft("
            f"currency={self.amount.currency!r}, <category-and-amount-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialMovementAllocationSetDraft:
    """First immutable classification version for one canonical Movement."""

    movement_id: UUID
    allocations: tuple[FinancialMovementAllocationDraft, ...]

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.movement_id)
        _validate_allocations(self.allocations)

    @property
    def currency(self) -> str:
        return self.allocations[0].amount.currency

    @property
    def total(self) -> Money:
        return _allocation_total(self.allocations)

    def canonical_allocations(self) -> tuple[FinancialMovementAllocationDraft, ...]:
        """Return allocations in a deterministic category-id order."""
        return tuple(sorted(self.allocations, key=lambda item: item.category_id.hex))

    def canonical_material(self) -> tuple[tuple[str, str, str], ...]:
        """Return order-independent material suitable for a request digest."""
        return tuple(item.canonical_material() for item in self.canonical_allocations())

    def __repr__(self) -> str:
        return (
            "FinancialMovementAllocationSetDraft("
            f"allocation_count={len(self.allocations)}, currency={self.currency!r}, "
            "<movement-and-amounts-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FinancialMovementAllocationRevisionDraft:
    """Replacement classification version that supersedes one prior set."""

    movement_id: UUID
    supersedes_id: UUID
    allocations: tuple[FinancialMovementAllocationDraft, ...]

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.movement_id)
        validate_financial_resource_id(self.supersedes_id)
        _validate_allocations(self.allocations)

    @property
    def currency(self) -> str:
        return self.allocations[0].amount.currency

    @property
    def total(self) -> Money:
        return _allocation_total(self.allocations)

    def canonical_allocations(self) -> tuple[FinancialMovementAllocationDraft, ...]:
        """Return allocations in a deterministic category-id order."""
        return tuple(sorted(self.allocations, key=lambda item: item.category_id.hex))

    def canonical_material(self) -> tuple[tuple[str, str, str], ...]:
        """Return order-independent material suitable for a request digest."""
        return tuple(item.canonical_material() for item in self.canonical_allocations())

    def __repr__(self) -> str:
        return (
            "FinancialMovementAllocationRevisionDraft("
            f"allocation_count={len(self.allocations)}, currency={self.currency!r}, "
            "<movement-predecessor-and-amounts-redacted>)"
        )


def is_category_audience_compatible_for_movement(
    *,
    movement_visibility_scope: FinancialVisibilityScope,
    movement_owner_operator_id: UUID,
    category_visibility_scope: FinancialVisibilityScope,
    category_owner_operator_id: UUID,
) -> bool:
    """Return whether category audience safely contains the Movement audience."""
    if not isinstance(movement_visibility_scope, FinancialVisibilityScope):
        raise TypeError("movement_visibility_scope must be FinancialVisibilityScope")
    if not isinstance(category_visibility_scope, FinancialVisibilityScope):
        raise TypeError("category_visibility_scope must be FinancialVisibilityScope")
    _require_uuid(movement_owner_operator_id, "movement_owner_operator_id")
    _require_uuid(category_owner_operator_id, "category_owner_operator_id")

    if category_visibility_scope is FinancialVisibilityScope.HOUSEHOLD:
        return True

    if movement_visibility_scope is FinancialVisibilityScope.PERSONAL:
        return (
            category_visibility_scope is FinancialVisibilityScope.PERSONAL
            and category_owner_operator_id == movement_owner_operator_id
        )

    # SHARED and HOUSEHOLD Movements have an audience wider than one owner.
    # Categories currently have no SHARED audience contract, so PERSONAL/SHARED
    # are both fail-closed here and only HOUSEHOLD is accepted above.
    return False


def _validate_allocations(
    allocations: tuple[FinancialMovementAllocationDraft, ...],
) -> None:
    if not isinstance(allocations, tuple):
        raise TypeError("allocations must be a tuple")
    if not allocations:
        raise ValueError("at least one allocation is required")
    if not all(
        isinstance(item, FinancialMovementAllocationDraft) for item in allocations
    ):
        raise TypeError("allocations must contain FinancialMovementAllocationDraft")

    category_ids = [item.category_id for item in allocations]
    if len(category_ids) != len(set(category_ids)):
        raise ValueError("allocation categories must be unique")

    currency = allocations[0].amount.currency
    if any(item.amount.currency != currency for item in allocations[1:]):
        raise ValueError("allocation currencies must match")

    first_positive = allocations[0].amount.amount > 0
    if any((item.amount.amount > 0) != first_positive for item in allocations[1:]):
        raise ValueError("allocation amounts must share the same sign")


def _allocation_total(
    allocations: tuple[FinancialMovementAllocationDraft, ...],
) -> Money:
    total = allocations[0].amount
    for item in allocations[1:]:
        total = total + item.amount
    return total


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


__all__ = [
    "FinancialMovementAllocationDraft",
    "FinancialMovementAllocationRevisionDraft",
    "FinancialMovementAllocationSetDraft",
    "is_category_audience_compatible_for_movement",
]
