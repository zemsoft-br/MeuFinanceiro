from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from meufinanceiro_finance.allocation_records import (
    FinancialMovementAllocationRecord,
    FinancialMovementAllocationSetRecord,
)
from meufinanceiro_finance.allocations import (
    FinancialMovementAllocationDraft,
    FinancialMovementAllocationRevisionDraft,
    FinancialMovementAllocationSetDraft,
)
from meufinanceiro_finance.money import Money


def _allocation(amount: str, *, category_id=None, currency: str = "BRL"):
    return FinancialMovementAllocationDraft(
        category_id=category_id or uuid4(),
        amount=Money(Decimal(amount), currency),
    )


def test_allocation_rejects_zero() -> None:
    with pytest.raises(ValueError, match="must not be zero"):
        _allocation("0")


def test_allocation_set_requires_tuple_and_non_empty() -> None:
    movement_id = uuid4()
    with pytest.raises(TypeError, match="must be a tuple"):
        FinancialMovementAllocationSetDraft(  # type: ignore[arg-type]
            movement_id=movement_id,
            allocations=[_allocation("-10")],
        )
    with pytest.raises(ValueError, match="at least one"):
        FinancialMovementAllocationSetDraft(
            movement_id=movement_id,
            allocations=(),
        )


def test_allocation_set_rejects_duplicate_categories() -> None:
    category_id = uuid4()
    with pytest.raises(ValueError, match="categories must be unique"):
        FinancialMovementAllocationSetDraft(
            movement_id=uuid4(),
            allocations=(
                _allocation("-7", category_id=category_id),
                _allocation("-3", category_id=category_id),
            ),
        )


def test_allocation_set_rejects_mixed_currency() -> None:
    with pytest.raises(ValueError, match="currencies must match"):
        FinancialMovementAllocationSetDraft(
            movement_id=uuid4(),
            allocations=(
                _allocation("-7", currency="BRL"),
                _allocation("-3", currency="USD"),
            ),
        )


def test_allocation_set_rejects_mixed_sign() -> None:
    with pytest.raises(ValueError, match="same sign"):
        FinancialMovementAllocationSetDraft(
            movement_id=uuid4(),
            allocations=(_allocation("-7"), _allocation("3")),
        )


def test_allocation_set_exposes_exact_total_without_float() -> None:
    draft = FinancialMovementAllocationSetDraft(
        movement_id=uuid4(),
        allocations=(_allocation("-70.125"), _allocation("-29.875")),
    )
    assert draft.total == Money(Decimal("-100"), "BRL")
    assert draft.currency == "BRL"


def test_canonical_order_is_independent_from_input_order() -> None:
    first = uuid4()
    second = uuid4()
    low, high = sorted((first, second), key=lambda value: value.hex)
    draft = FinancialMovementAllocationSetDraft(
        movement_id=uuid4(),
        allocations=(
            _allocation("-3", category_id=high),
            _allocation("-7", category_id=low),
        ),
    )
    assert tuple(item.category_id for item in draft.canonical_allocations()) == (low, high)


def test_revision_requires_valid_predecessor_and_reuses_same_invariants() -> None:
    revision = FinancialMovementAllocationRevisionDraft(
        movement_id=uuid4(),
        supersedes_id=uuid4(),
        allocations=(_allocation("25"), _allocation("75")),
    )
    assert revision.total == Money(Decimal("100"), "BRL")


def test_records_require_consistent_revision_shape_and_set_identity() -> None:
    set_id = uuid4()
    movement_id = uuid4()
    operator_id = uuid4()
    now = datetime.now(UTC)
    allocation = FinancialMovementAllocationRecord(
        id=uuid4(),
        allocation_set_id=set_id,
        category_id=uuid4(),
        amount=Money(Decimal("-100"), "BRL"),
        created_at=now,
    )
    record = FinancialMovementAllocationSetRecord(
        id=set_id,
        movement_id=movement_id,
        revision=1,
        supersedes_id=None,
        created_by_operator_id=operator_id,
        created_at=now,
        allocations=(allocation,),
    )
    assert record.revision == 1

    with pytest.raises(ValueError, match="first revision"):
        FinancialMovementAllocationSetRecord(
            id=set_id,
            movement_id=movement_id,
            revision=1,
            supersedes_id=uuid4(),
            created_by_operator_id=operator_id,
            created_at=now,
            allocations=(allocation,),
        )


def test_repr_redacts_financial_and_identity_material() -> None:
    category_id = uuid4()
    movement_id = uuid4()
    allocation = _allocation("-123.45", category_id=category_id)
    draft = FinancialMovementAllocationSetDraft(
        movement_id=movement_id,
        allocations=(allocation,),
    )
    rendered = repr(draft)
    assert "123.45" not in rendered
    assert str(category_id) not in rendered
    assert str(movement_id) not in rendered
