from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid1, uuid4

import pytest

from meufinanceiro_finance import (
    FinancialMovementRecord,
    FinancialMovementRole,
    FinancialOpeningBalanceDraft,
    FinancialOpeningBalanceRecord,
    FinancialResultEffect,
    Money,
    new_financial_idempotency_key,
    new_financial_resource_id,
    validate_financial_idempotency_key,
)


def test_finance_package_exports_ledger_and_opening_balance_contracts() -> None:
    opening = FinancialOpeningBalanceDraft(
        amount=Money(Decimal("0"), "BRL"),
        effective_date=date(2026, 8, 1),
    )
    assert opening.amount.amount == Decimal("0")
    assert FinancialOpeningBalanceRecord is not None
    assert FinancialMovementRecord is not None


def test_financial_idempotency_key_is_uuid4_but_not_resource_identity() -> None:
    key = new_financial_idempotency_key()

    assert key.version == 4
    assert validate_financial_idempotency_key(key) == key
    assert new_financial_resource_id() != key

    with pytest.raises(TypeError, match="idempotency_key must be UUID"):
        validate_financial_idempotency_key(str(key))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="UUID v4"):
        validate_financial_idempotency_key(uuid1())


def test_standard_persisted_record_enforces_sign_and_redacts_sensitive_fields() -> None:
    movement_id = new_financial_resource_id()
    account_id = new_financial_resource_id()
    operator_id = uuid4()
    record = FinancialMovementRecord(
        id=movement_id,
        account_id=account_id,
        amount=Money(Decimal("123.45"), "BRL"),
        result_effect=FinancialResultEffect.INCOME,
        role=FinancialMovementRole.STANDARD,
        effective_date=date(2026, 8, 10),
        competence_date=date(2026, 8, 1),
        description="Receita sintética",
        reversal_of_id=None,
        reversal_reason=None,
        created_by_operator_id=operator_id,
        created_at=datetime(2026, 8, 11, 4, 30, tzinfo=UTC),
    )

    rendered = repr(record)
    assert "123.45" not in rendered
    assert str(movement_id) not in rendered
    assert str(account_id) not in rendered
    assert str(operator_id) not in rendered
    assert "Receita sintética" not in rendered
    assert "INCOME" in rendered
    assert "BRL" in rendered

    with pytest.raises(ValueError, match="INCOME STANDARD"):
        FinancialMovementRecord(
            id=new_financial_resource_id(),
            account_id=account_id,
            amount=Money(Decimal("-1"), "BRL"),
            result_effect=FinancialResultEffect.INCOME,
            role=FinancialMovementRole.STANDARD,
            effective_date=date(2026, 8, 10),
            competence_date=date(2026, 8, 1),
            description="Inválido",
            reversal_of_id=None,
            reversal_reason=None,
            created_by_operator_id=operator_id,
            created_at=datetime(2026, 8, 11, 4, 30, tzinfo=UTC),
        )


def test_reversal_persisted_record_requires_original_and_reason() -> None:
    original_id = new_financial_resource_id()
    record = FinancialMovementRecord(
        id=new_financial_resource_id(),
        account_id=new_financial_resource_id(),
        amount=Money(Decimal("-25"), "BRL"),
        result_effect=FinancialResultEffect.INCOME,
        role=FinancialMovementRole.REVERSAL,
        effective_date=date(2026, 8, 11),
        competence_date=date(2026, 8, 1),
        description=None,
        reversal_of_id=original_id,
        reversal_reason="  Correção integral  ",
        created_by_operator_id=uuid4(),
        created_at=datetime(2026, 8, 11, 4, 31, tzinfo=UTC),
    )

    assert record.reversal_reason == "Correção integral"
    assert record.reversal_of_id == original_id

    with pytest.raises(ValueError, match="requires reversal_of_id"):
        FinancialMovementRecord(
            id=new_financial_resource_id(),
            account_id=new_financial_resource_id(),
            amount=Money(Decimal("-25"), "BRL"),
            result_effect=FinancialResultEffect.INCOME,
            role=FinancialMovementRole.REVERSAL,
            effective_date=date(2026, 8, 11),
            competence_date=date(2026, 8, 1),
            description=None,
            reversal_of_id=None,
            reversal_reason="Correção integral",
            created_by_operator_id=uuid4(),
            created_at=datetime(2026, 8, 11, 4, 31, tzinfo=UTC),
        )
