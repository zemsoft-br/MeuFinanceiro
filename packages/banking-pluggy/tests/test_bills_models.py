from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from meufinanceiro_banking_pluggy.bills import (
    PluggyCreditCardBillSnapshot,
    PluggyCreditCardBillState,
)


def test_bill_snapshot_normalizes_currency_and_redacts_repr() -> None:
    snapshot = PluggyCreditCardBillSnapshot(
        bill_id="bill-1",
        account_id="account-card",
        state=PluggyCreditCardBillState.OPEN,
        due_date=date(2026, 9, 10),
        close_date=date(2026, 9, 3),
        total_amount=Decimal("100.00"),
        minimum_payment=Decimal("25.00"),
        currency="brl",
    )

    assert snapshot.currency == "BRL"
    assert repr(snapshot) == "PluggyCreditCardBillSnapshot(<bill-data-redacted>)"
    assert "bill-1" not in repr(snapshot)
    assert "account-card" not in repr(snapshot)


def test_bill_snapshot_rejects_invalid_economic_shape() -> None:
    with pytest.raises(ValueError, match="minimum_payment must not exceed total_amount"):
        PluggyCreditCardBillSnapshot(
            bill_id="bill-1",
            account_id="account-card",
            state=PluggyCreditCardBillState.CLOSED,
            due_date=date(2026, 9, 10),
            total_amount=Decimal("100"),
            minimum_payment=Decimal("101"),
            currency="BRL",
        )

    with pytest.raises(ValueError, match="finite and non-negative"):
        PluggyCreditCardBillSnapshot(
            bill_id="bill-1",
            account_id="account-card",
            state=PluggyCreditCardBillState.CLOSED,
            due_date=date(2026, 9, 10),
            total_amount=Decimal("NaN"),
            currency="BRL",
        )


def test_bill_snapshot_rejects_datetime_where_date_is_required() -> None:
    with pytest.raises(TypeError, match="due_date must be date"):
        PluggyCreditCardBillSnapshot(
            bill_id="bill-1",
            account_id="account-card",
            state=PluggyCreditCardBillState.UNKNOWN,
            due_date=datetime(2026, 9, 10, tzinfo=UTC),
            total_amount=Decimal("10"),
            currency="BRL",
        )
