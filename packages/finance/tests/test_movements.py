from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from meufinanceiro_finance.ids import new_financial_resource_id
from meufinanceiro_finance.money import Money
from meufinanceiro_finance.movements import (
    FinancialMovementDraft,
    FinancialMovementReversalDraft,
    FinancialMovementRole,
    FinancialResultEffect,
)


def _movement(
    amount: str,
    effect: FinancialResultEffect,
) -> FinancialMovementDraft:
    return FinancialMovementDraft(
        account_id=new_financial_resource_id(),
        amount=Money(Decimal(amount), "BRL"),
        result_effect=effect,
        effective_date=date(2026, 8, 10),
        competence_date=date(2026, 8, 1),
        description="  Movimento sintético  ",
    )


def test_standard_income_requires_positive_amount() -> None:
    movement = _movement("100.25", FinancialResultEffect.INCOME)
    assert movement.amount.amount == Decimal("100.25")
    assert movement.description == "Movimento sintético"

    for invalid in ("0", "-1"):
        with pytest.raises(ValueError):
            _movement(invalid, FinancialResultEffect.INCOME)


def test_standard_expense_requires_negative_amount() -> None:
    movement = _movement("-80.10", FinancialResultEffect.EXPENSE)
    assert movement.amount.amount == Decimal("-80.10")

    for invalid in ("0", "1"):
        with pytest.raises(ValueError):
            _movement(invalid, FinancialResultEffect.EXPENSE)


def test_neutral_accepts_both_signs_but_never_zero() -> None:
    assert _movement("250", FinancialResultEffect.NEUTRAL).amount.amount > 0
    assert _movement("-250", FinancialResultEffect.NEUTRAL).amount.amount < 0

    with pytest.raises(ValueError, match="must not be zero"):
        _movement("0", FinancialResultEffect.NEUTRAL)


def test_financial_dates_are_explicit_plain_dates() -> None:
    with pytest.raises(TypeError, match="effective_date must be date"):
        FinancialMovementDraft(
            account_id=new_financial_resource_id(),
            amount=Money(Decimal("10"), "BRL"),
            result_effect=FinancialResultEffect.INCOME,
            effective_date=datetime(2026, 8, 10, 12, 0),  # type: ignore[arg-type]
            competence_date=date(2026, 8, 1),
            description="Sintético",
        )

    with pytest.raises(TypeError, match="competence_date must be date"):
        FinancialMovementDraft(
            account_id=new_financial_resource_id(),
            amount=Money(Decimal("10"), "BRL"),
            result_effect=FinancialResultEffect.INCOME,
            effective_date=date(2026, 8, 10),
            competence_date=datetime(2026, 8, 1, 12, 0),  # type: ignore[arg-type]
            description="Sintético",
        )


def test_description_is_required_bounded_and_control_character_free() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        FinancialMovementDraft(
            account_id=new_financial_resource_id(),
            amount=Money(Decimal("10"), "BRL"),
            result_effect=FinancialResultEffect.INCOME,
            effective_date=date(2026, 8, 10),
            competence_date=date(2026, 8, 1),
            description="   ",
        )

    with pytest.raises(ValueError, match="control characters"):
        FinancialMovementDraft(
            account_id=new_financial_resource_id(),
            amount=Money(Decimal("10"), "BRL"),
            result_effect=FinancialResultEffect.INCOME,
            effective_date=date(2026, 8, 10),
            competence_date=date(2026, 8, 1),
            description="Linha\nsecreta",
        )

    with pytest.raises(ValueError, match="exceeds 256"):
        FinancialMovementDraft(
            account_id=new_financial_resource_id(),
            amount=Money(Decimal("10"), "BRL"),
            result_effect=FinancialResultEffect.INCOME,
            effective_date=date(2026, 8, 10),
            competence_date=date(2026, 8, 1),
            description="x" * 257,
        )


def test_movement_requires_local_financial_account_uuid() -> None:
    account_id = new_financial_resource_id()
    with pytest.raises(TypeError):
        FinancialMovementDraft(  # type: ignore[arg-type]
            account_id=str(account_id),
            amount=Money(Decimal("10"), "BRL"),
            result_effect=FinancialResultEffect.INCOME,
            effective_date=date(2026, 8, 10),
            competence_date=date(2026, 8, 1),
            description="Sintético",
        )


def test_reversal_draft_contains_no_caller_supplied_financial_effect() -> None:
    reversal = FinancialMovementReversalDraft(
        movement_id=new_financial_resource_id(),
        effective_date=date(2026, 8, 11),
        competence_date=date(2026, 8, 1),
        reason="  Correção sintética  ",
    )

    assert reversal.reason == "Correção sintética"
    assert not hasattr(reversal, "amount")
    assert not hasattr(reversal, "account_id")
    assert not hasattr(reversal, "currency")
    assert not hasattr(reversal, "result_effect")


def test_reversal_reason_and_dates_are_validated() -> None:
    movement_id = new_financial_resource_id()
    with pytest.raises(ValueError, match="reason must not be empty"):
        FinancialMovementReversalDraft(
            movement_id=movement_id,
            effective_date=date(2026, 8, 11),
            competence_date=date(2026, 8, 1),
            reason=" ",
        )

    with pytest.raises(TypeError):
        FinancialMovementReversalDraft(  # type: ignore[arg-type]
            movement_id=str(movement_id),
            effective_date=date(2026, 8, 11),
            competence_date=date(2026, 8, 1),
            reason="Correção",
        )


def test_repr_redacts_movement_financial_material() -> None:
    movement = _movement("123456.78", FinancialResultEffect.INCOME)
    rendered = repr(movement)

    assert "123456.78" not in rendered
    assert str(movement.account_id) not in rendered
    assert movement.description not in rendered
    assert "INCOME" in rendered
    assert "BRL" in rendered

    reversal = FinancialMovementReversalDraft(
        movement_id=new_financial_resource_id(),
        effective_date=date(2026, 8, 11),
        competence_date=date(2026, 8, 1),
        reason="Motivo sensível",
    )
    reversed_repr = repr(reversal)
    assert str(reversal.movement_id) not in reversed_repr
    assert reversal.reason not in reversed_repr


def test_movement_roles_are_closed_and_explicit() -> None:
    assert FinancialMovementRole.STANDARD.value == "STANDARD"
    assert FinancialMovementRole.REVERSAL.value == "REVERSAL"
