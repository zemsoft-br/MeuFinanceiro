from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from meufinanceiro_finance.ids import new_financial_resource_id
from meufinanceiro_finance.money import Money
from meufinanceiro_finance.movements import FinancialResultEffect
from meufinanceiro_finance.transfers import (
    FinancialTransferDraft,
    FinancialTransferReversalDraft,
    FinancialTransferRole,
)


def _transfer(amount: str = "100.25") -> FinancialTransferDraft:
    return FinancialTransferDraft(
        source_account_id=new_financial_resource_id(),
        destination_account_id=new_financial_resource_id(),
        magnitude=Money(Decimal(amount), "BRL"),
        effective_date=date(2026, 8, 13),
        competence_date=date(2026, 8, 1),
        description="  Transferência sintética  ",
    )


def test_transfer_maps_to_two_opposite_neutral_movements() -> None:
    transfer = _transfer("100.25")
    source, destination = transfer.to_movement_drafts()

    assert source.account_id == transfer.source_account_id
    assert destination.account_id == transfer.destination_account_id
    assert source.amount.amount == Decimal("-100.25")
    assert destination.amount.amount == Decimal("100.25")
    assert source.amount.currency == destination.amount.currency == "BRL"
    assert source.result_effect is FinancialResultEffect.NEUTRAL
    assert destination.result_effect is FinancialResultEffect.NEUTRAL
    assert source.amount.amount + destination.amount.amount == Decimal("0")
    assert source.effective_date == destination.effective_date == date(2026, 8, 13)
    assert source.competence_date == destination.competence_date == date(2026, 8, 1)
    assert source.description == destination.description == "Transferência sintética"
    assert transfer.description == "Transferência sintética"


def test_transfer_requires_distinct_accounts() -> None:
    account_id = new_financial_resource_id()
    with pytest.raises(ValueError, match="accounts must be distinct"):
        FinancialTransferDraft(
            source_account_id=account_id,
            destination_account_id=account_id,
            magnitude=Money(Decimal("10"), "BRL"),
            effective_date=date(2026, 8, 13),
            competence_date=date(2026, 8, 1),
            description="Sintético",
        )


@pytest.mark.parametrize("amount", ["0", "-0.01", "-100"])
def test_transfer_requires_positive_magnitude(amount: str) -> None:
    with pytest.raises(ValueError, match="magnitude must be positive"):
        _transfer(amount)


def test_transfer_reuses_movement_date_and_description_validation() -> None:
    with pytest.raises(TypeError, match="effective_date must be date"):
        FinancialTransferDraft(
            source_account_id=new_financial_resource_id(),
            destination_account_id=new_financial_resource_id(),
            magnitude=Money(Decimal("10"), "BRL"),
            effective_date=datetime(2026, 8, 13, 12, 0),  # type: ignore[arg-type]
            competence_date=date(2026, 8, 1),
            description="Sintético",
        )

    with pytest.raises(ValueError, match="description must not be empty"):
        FinancialTransferDraft(
            source_account_id=new_financial_resource_id(),
            destination_account_id=new_financial_resource_id(),
            magnitude=Money(Decimal("10"), "BRL"),
            effective_date=date(2026, 8, 13),
            competence_date=date(2026, 8, 1),
            description="  ",
        )


def test_transfer_repr_redacts_financial_material() -> None:
    transfer = _transfer("123456.78")
    rendered = repr(transfer)

    assert "123456.78" not in rendered
    assert str(transfer.source_account_id) not in rendered
    assert str(transfer.destination_account_id) not in rendered
    assert transfer.description not in rendered
    assert "BRL" in rendered


def test_transfer_reversal_draft_contains_no_caller_supplied_effects() -> None:
    reversal = FinancialTransferReversalDraft(
        transfer_id=new_financial_resource_id(),
        effective_date=date(2026, 8, 14),
        competence_date=date(2026, 8, 1),
        reason="  Correção sintética  ",
    )

    assert reversal.reason == "Correção sintética"
    assert not hasattr(reversal, "magnitude")
    assert not hasattr(reversal, "source_account_id")
    assert not hasattr(reversal, "destination_account_id")
    assert not hasattr(reversal, "currency")


def test_transfer_reversal_validates_dates_reason_and_repr() -> None:
    transfer_id = new_financial_resource_id()
    with pytest.raises(ValueError, match="reason must not be empty"):
        FinancialTransferReversalDraft(
            transfer_id=transfer_id,
            effective_date=date(2026, 8, 14),
            competence_date=date(2026, 8, 1),
            reason=" ",
        )

    with pytest.raises(TypeError, match="competence_date must be date"):
        FinancialTransferReversalDraft(
            transfer_id=transfer_id,
            effective_date=date(2026, 8, 14),
            competence_date=datetime(2026, 8, 1, 12, 0),  # type: ignore[arg-type]
            reason="Correção",
        )

    reversal = FinancialTransferReversalDraft(
        transfer_id=transfer_id,
        effective_date=date(2026, 8, 14),
        competence_date=date(2026, 8, 1),
        reason="Motivo sensível",
    )
    rendered = repr(reversal)
    assert str(transfer_id) not in rendered
    assert reversal.reason not in rendered


def test_transfer_roles_are_closed_and_explicit() -> None:
    assert FinancialTransferRole.STANDARD.value == "STANDARD"
    assert FinancialTransferRole.REVERSAL.value == "REVERSAL"
