from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from meufinanceiro_banking_pluggy.loans import PluggyLoanSnapshot

NOW = datetime(2026, 9, 19, 3, 0, tzinfo=UTC)


def _snapshot(
    *,
    loan_id: str = "loan-1",
    item_id: str = "item-1",
    kind: str = "loan",
    outstanding_balance: Decimal = Decimal("2500.00"),
    currency: str = "brl",
    as_of: datetime = NOW,
    contracted_at: date | None = date(2025, 1, 10),
    due_date: date | None = date(2028, 1, 10),
) -> PluggyLoanSnapshot:
    return PluggyLoanSnapshot(
        loan_id=loan_id,
        item_id=item_id,
        kind=kind,
        outstanding_balance=outstanding_balance,
        currency=currency,
        as_of=as_of,
        contracted_at=contracted_at,
        due_date=due_date,
    )


def test_loan_snapshot_normalizes_safe_fields_and_redacts_repr() -> None:
    value = _snapshot()

    assert value.kind == "LOAN"
    assert value.currency == "BRL"
    assert value.outstanding_balance == Decimal("2500.00")
    assert repr(value) == "PluggyLoanSnapshot(<loan-data-redacted>)"
    assert "loan-1" not in repr(value)
    assert "2500" not in repr(value)


@pytest.mark.parametrize(
    "balance",
    [Decimal("-0.01"), Decimal("NaN"), Decimal("Infinity")],
)
def test_loan_snapshot_rejects_invalid_outstanding_balance(
    balance: Decimal,
) -> None:
    with pytest.raises(ValueError, match="finite and non-negative"):
        _snapshot(outstanding_balance=balance)


def test_loan_snapshot_requires_aware_reference_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _snapshot(as_of=datetime(2026, 9, 19, 3, 0))


def test_loan_snapshot_accepts_missing_optional_contract_dates() -> None:
    value = _snapshot(contracted_at=None, due_date=None)

    assert value.contracted_at is None
    assert value.due_date is None


def test_loan_snapshot_rejects_due_date_before_contract_date() -> None:
    with pytest.raises(ValueError, match="due_date must not be before contracted_at"):
        _snapshot(
            contracted_at=date(2026, 1, 10),
            due_date=date(2025, 1, 10),
        )


def test_loan_snapshot_rejects_invalid_currency() -> None:
    with pytest.raises(ValueError, match="three-letter ASCII"):
        _snapshot(currency="REAL")
