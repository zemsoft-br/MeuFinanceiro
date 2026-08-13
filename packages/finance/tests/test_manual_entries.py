from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from meufinanceiro_finance.ids import new_financial_resource_id
from meufinanceiro_finance.manual_entries import (
    FinancialManualEntryDraft,
    FinancialManualEntryService,
    FinancialManualEntryType,
)
from meufinanceiro_finance.money import Money
from meufinanceiro_finance.movement_records import FinancialMovementRecord
from meufinanceiro_finance.movements import (
    FinancialMovementDraft,
    FinancialMovementRole,
    FinancialResultEffect,
)
from meufinanceiro_finance.operation_ids import new_financial_idempotency_key


def _draft(
    entry_type: FinancialManualEntryType,
    amount: str = "10.50",
) -> FinancialManualEntryDraft:
    return FinancialManualEntryDraft(
        account_id=new_financial_resource_id(),
        magnitude=Money(Decimal(amount), "BRL"),
        entry_type=entry_type,
        effective_date=date(2026, 8, 13),
        competence_date=date(2026, 8, 1),
        description="  Lançamento sintético  ",
    )


def test_income_maps_positive_magnitude_to_positive_income() -> None:
    draft = _draft(FinancialManualEntryType.INCOME, "100.25")
    movement = draft.to_movement_draft()

    assert movement.result_effect is FinancialResultEffect.INCOME
    assert movement.amount.amount == Decimal("100.25")
    assert movement.amount.currency == "BRL"
    assert movement.description == "Lançamento sintético"


def test_expense_maps_positive_magnitude_to_negative_expense() -> None:
    draft = _draft(FinancialManualEntryType.EXPENSE, "40")
    movement = draft.to_movement_draft()

    assert movement.result_effect is FinancialResultEffect.EXPENSE
    assert movement.amount.amount == Decimal("-40")
    assert movement.amount.currency == "BRL"


@pytest.mark.parametrize("amount", ["0", "-0.01", "-100"])
def test_manual_entry_rejects_non_positive_magnitude(amount: str) -> None:
    with pytest.raises(ValueError, match="magnitude must be positive"):
        _draft(FinancialManualEntryType.INCOME, amount)


def test_manual_entry_reuses_existing_date_and_description_contracts() -> None:
    with pytest.raises(TypeError, match="effective_date must be date"):
        FinancialManualEntryDraft(
            account_id=new_financial_resource_id(),
            magnitude=Money(Decimal("10"), "BRL"),
            entry_type=FinancialManualEntryType.INCOME,
            effective_date=datetime(2026, 8, 13, 1, 0),  # type: ignore[arg-type]
            competence_date=date(2026, 8, 1),
            description="Sintético",
        )

    with pytest.raises(ValueError, match="description must not be empty"):
        FinancialManualEntryDraft(
            account_id=new_financial_resource_id(),
            magnitude=Money(Decimal("10"), "BRL"),
            entry_type=FinancialManualEntryType.INCOME,
            effective_date=date(2026, 8, 13),
            competence_date=date(2026, 8, 1),
            description="  ",
        )


def test_manual_entry_requires_explicit_supported_type() -> None:
    with pytest.raises(TypeError, match="entry_type must be FinancialManualEntryType"):
        FinancialManualEntryDraft(
            account_id=new_financial_resource_id(),
            magnitude=Money(Decimal("10"), "BRL"),
            entry_type="INCOME",  # type: ignore[arg-type]
            effective_date=date(2026, 8, 13),
            competence_date=date(2026, 8, 1),
            description="Sintético",
        )


def test_repr_redacts_sensitive_manual_entry_material() -> None:
    draft = _draft(FinancialManualEntryType.EXPENSE, "123456.78")
    rendered = repr(draft)

    assert "123456.78" not in rendered
    assert str(draft.account_id) not in rendered
    assert draft.description not in rendered
    assert "EXPENSE" in rendered
    assert "BRL" in rendered


class FakeMovementStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create_movement(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialMovementDraft,
    ) -> FinancialMovementRecord:
        self.calls.append(
            {
                "installation_id": installation_id,
                "residence_id": residence_id,
                "operator_id": operator_id,
                "idempotency_key": idempotency_key,
                "draft": draft,
            }
        )
        return FinancialMovementRecord(
            id=new_financial_resource_id(),
            account_id=draft.account_id,
            amount=draft.amount,
            result_effect=draft.result_effect,
            role=FinancialMovementRole.STANDARD,
            effective_date=draft.effective_date,
            competence_date=draft.competence_date,
            description=draft.description,
            reversal_of_id=None,
            reversal_reason=None,
            created_by_operator_id=operator_id,
            created_at=datetime.now(UTC),
        )


def test_service_delegates_exactly_once_to_canonical_movement_boundary() -> None:
    store = FakeMovementStore()
    service = FinancialManualEntryService(store)
    installation_id = uuid4()
    residence_id = uuid4()
    operator_id = uuid4()
    idempotency_key = new_financial_idempotency_key()
    draft = _draft(FinancialManualEntryType.EXPENSE, "80")

    result = service.record(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
        idempotency_key=idempotency_key,
        draft=draft,
    )

    assert len(store.calls) == 1
    call = store.calls[0]
    assert call["installation_id"] == installation_id
    assert call["residence_id"] == residence_id
    assert call["operator_id"] == operator_id
    assert call["idempotency_key"] == idempotency_key
    movement = call["draft"]
    assert isinstance(movement, FinancialMovementDraft)
    assert movement.amount.amount == Decimal("-80")
    assert movement.result_effect is FinancialResultEffect.EXPENSE
    assert result.amount.amount == Decimal("-80")


def test_service_rejects_non_uuid4_idempotency_key_before_store_call() -> None:
    store = FakeMovementStore()
    service = FinancialManualEntryService(store)

    with pytest.raises(ValueError, match="UUID v4"):
        service.record(
            installation_id=uuid4(),
            residence_id=uuid4(),
            operator_id=uuid4(),
            idempotency_key=UUID("12345678-1234-1234-1234-123456789abc"),
            draft=_draft(FinancialManualEntryType.INCOME),
        )

    assert store.calls == []
