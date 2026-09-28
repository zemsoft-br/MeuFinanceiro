from __future__ import annotations

from datetime import UTC, datetime

import pytest

from meufinanceiro_finance.ids import new_financial_resource_id
from meufinanceiro_finance.transfer_records import FinancialTransferRecord
from meufinanceiro_finance.transfers import FinancialTransferRole


def _record(role: FinancialTransferRole) -> FinancialTransferRecord:
    return FinancialTransferRecord(
        id=new_financial_resource_id(),
        source_account_id=new_financial_resource_id(),
        destination_account_id=new_financial_resource_id(),
        currency="BRL",
        source_movement_id=new_financial_resource_id(),
        destination_movement_id=new_financial_resource_id(),
        role=role,
        reversal_of_id=(
            None
            if role is FinancialTransferRole.STANDARD
            else new_financial_resource_id()
        ),
        created_by_operator_id=new_financial_resource_id(),
        created_at=datetime(2026, 8, 13, 6, 0, tzinfo=UTC),
    )


def test_transfer_record_accepts_standard_and_reversal_shapes() -> None:
    standard = _record(FinancialTransferRole.STANDARD)
    reversal = _record(FinancialTransferRole.REVERSAL)

    assert standard.reversal_of_id is None
    assert reversal.reversal_of_id is not None
    assert standard.currency == reversal.currency == "BRL"


def test_transfer_record_rejects_same_accounts_or_movements() -> None:
    account_id = new_financial_resource_id()
    with pytest.raises(ValueError, match="accounts must be distinct"):
        FinancialTransferRecord(
            id=new_financial_resource_id(),
            source_account_id=account_id,
            destination_account_id=account_id,
            currency="BRL",
            source_movement_id=new_financial_resource_id(),
            destination_movement_id=new_financial_resource_id(),
            role=FinancialTransferRole.STANDARD,
            reversal_of_id=None,
            created_by_operator_id=new_financial_resource_id(),
            created_at=datetime.now(UTC),
        )

    movement_id = new_financial_resource_id()
    with pytest.raises(ValueError, match="Movement legs must be distinct"):
        FinancialTransferRecord(
            id=new_financial_resource_id(),
            source_account_id=new_financial_resource_id(),
            destination_account_id=new_financial_resource_id(),
            currency="BRL",
            source_movement_id=movement_id,
            destination_movement_id=movement_id,
            role=FinancialTransferRole.STANDARD,
            reversal_of_id=None,
            created_by_operator_id=new_financial_resource_id(),
            created_at=datetime.now(UTC),
        )


def test_transfer_record_role_shape_is_fail_closed() -> None:
    with pytest.raises(ValueError, match="must not reference"):
        FinancialTransferRecord(
            id=new_financial_resource_id(),
            source_account_id=new_financial_resource_id(),
            destination_account_id=new_financial_resource_id(),
            currency="BRL",
            source_movement_id=new_financial_resource_id(),
            destination_movement_id=new_financial_resource_id(),
            role=FinancialTransferRole.STANDARD,
            reversal_of_id=new_financial_resource_id(),
            created_by_operator_id=new_financial_resource_id(),
            created_at=datetime.now(UTC),
        )


def test_transfer_record_repr_redacts_linked_identities() -> None:
    record = _record(FinancialTransferRole.REVERSAL)
    rendered = repr(record)

    assert str(record.id) not in rendered
    assert str(record.source_account_id) not in rendered
    assert str(record.destination_account_id) not in rendered
    assert str(record.source_movement_id) not in rendered
    assert str(record.destination_movement_id) not in rendered
    assert "REVERSAL" in rendered
    assert "BRL" in rendered
