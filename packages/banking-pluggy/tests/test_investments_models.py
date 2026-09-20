from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from meufinanceiro_banking_pluggy.investments import PluggyInvestmentSnapshot

NOW = datetime(2026, 9, 19, 3, 0, tzinfo=UTC)


def _snapshot(
    *,
    investment_id: str = "investment-1",
    item_id: str = "item-1",
    name: str = "Synthetic Fund",
    kind: str = "mutual_fund",
    balance: Decimal = Decimal("1250.50"),
    currency: str = "brl",
    as_of: datetime = NOW,
) -> PluggyInvestmentSnapshot:
    return PluggyInvestmentSnapshot(
        investment_id=investment_id,
        item_id=item_id,
        name=name,
        kind=kind,
        balance=balance,
        currency=currency,
        as_of=as_of,
    )


def test_investment_snapshot_normalizes_safe_fields_and_redacts_repr() -> None:
    value = _snapshot()

    assert value.kind == "MUTUAL_FUND"
    assert value.currency == "BRL"
    assert value.balance == Decimal("1250.50")
    assert repr(value) == "PluggyInvestmentSnapshot(<investment-data-redacted>)"
    assert "investment-1" not in repr(value)
    assert "Synthetic Fund" not in repr(value)


@pytest.mark.parametrize(
    "balance",
    [Decimal("-0.01"), Decimal("NaN"), Decimal("Infinity")],
)
def test_investment_snapshot_rejects_invalid_balance(balance: Decimal) -> None:
    with pytest.raises(ValueError, match="finite and non-negative"):
        _snapshot(balance=balance)


def test_investment_snapshot_requires_timezone_aware_reference_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _snapshot(as_of=datetime(2026, 9, 19, 3, 0))


def test_investment_snapshot_rejects_invalid_currency() -> None:
    with pytest.raises(ValueError, match="three-letter ASCII"):
        _snapshot(currency="REAL")


def test_investment_snapshot_rejects_blank_allowlisted_text() -> None:
    with pytest.raises(ValueError, match="name is invalid"):
        _snapshot(name="   ")
    with pytest.raises(ValueError, match="kind is invalid"):
        _snapshot(kind="   ")
