from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from meufinanceiro_finance import (
    FinancialOpeningBalanceDraft,
    FinancialOpeningBalanceRecord,
    Money,
    new_financial_resource_id,
)

NOW = datetime(2026, 8, 11, 3, 30, tzinfo=UTC)


def test_opening_balance_draft_accepts_positive_zero_and_negative_money() -> None:
    for amount in (Decimal("100.00"), Decimal("0"), Decimal("-50.25")):
        draft = FinancialOpeningBalanceDraft(
            amount=Money(amount, "BRL"),
            effective_date=date(2026, 8, 1),
        )
        assert draft.amount.amount == amount


def test_opening_balance_draft_requires_money_and_plain_date() -> None:
    with pytest.raises(TypeError, match="amount must be Money"):
        FinancialOpeningBalanceDraft(  # type: ignore[arg-type]
            amount=Decimal("10"),
            effective_date=date(2026, 8, 1),
        )

    with pytest.raises(TypeError, match="effective_date must be date"):
        FinancialOpeningBalanceDraft(
            amount=Money(Decimal("10"), "BRL"),
            effective_date=NOW,  # type: ignore[arg-type]
        )


def test_opening_balance_record_redacts_amount_and_identities() -> None:
    record = FinancialOpeningBalanceRecord(
        id=new_financial_resource_id(),
        residence_id=uuid4(),
        account_id=new_financial_resource_id(),
        amount=Money(Decimal("987654.32"), "BRL"),
        effective_date=date(2026, 8, 1),
        created_by_operator_id=uuid4(),
        created_at=NOW,
    )

    rendered = repr(record)
    assert "987654.32" not in rendered
    assert str(record.id) not in rendered
    assert str(record.residence_id) not in rendered
    assert str(record.account_id) not in rendered
    assert str(record.created_by_operator_id) not in rendered
    assert "BRL" in rendered
    assert "2026" in rendered


def test_opening_balance_record_requires_aware_creation_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FinancialOpeningBalanceRecord(
            id=new_financial_resource_id(),
            residence_id=uuid4(),
            account_id=new_financial_resource_id(),
            amount=Money(Decimal("10"), "BRL"),
            effective_date=date(2026, 8, 1),
            created_by_operator_id=uuid4(),
            created_at=datetime(2026, 8, 11, 3, 30),
        )
