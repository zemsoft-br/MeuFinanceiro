"""Provider-neutral manual income/expense use cases for the canonical ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from meufinanceiro_finance.ids import validate_financial_resource_id
from meufinanceiro_finance.money import Money
from meufinanceiro_finance.movement_records import FinancialMovementRecord
from meufinanceiro_finance.movements import (
    FinancialMovementDraft,
    FinancialResultEffect,
)
from meufinanceiro_finance.operation_ids import validate_financial_idempotency_key


class FinancialManualEntryType(StrEnum):
    """Supported manual economic-result entries."""

    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialManualEntryDraft:
    """Positive-magnitude intent for one manual income or expense."""

    account_id: UUID
    magnitude: Money
    entry_type: FinancialManualEntryType
    effective_date: date
    competence_date: date
    description: str

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.account_id)
        if not isinstance(self.magnitude, Money):
            raise TypeError("magnitude must be Money")
        if self.magnitude.amount <= 0:
            raise ValueError("manual entry magnitude must be positive")
        if not isinstance(self.entry_type, FinancialManualEntryType):
            raise TypeError("entry_type must be FinancialManualEntryType")

        movement = self.to_movement_draft()
        object.__setattr__(self, "description", movement.description)

    def to_movement_draft(self) -> FinancialMovementDraft:
        """Translate manual intent into the signed canonical Movement contract."""
        if self.entry_type is FinancialManualEntryType.INCOME:
            amount = self.magnitude
            result_effect = FinancialResultEffect.INCOME
        else:
            amount = -self.magnitude
            result_effect = FinancialResultEffect.EXPENSE

        return FinancialMovementDraft(
            account_id=self.account_id,
            amount=amount,
            result_effect=result_effect,
            effective_date=self.effective_date,
            competence_date=self.competence_date,
            description=self.description,
        )

    def __repr__(self) -> str:
        return (
            "FinancialManualEntryDraft("
            f"entry_type={self.entry_type.value!r}, "
            f"currency={self.magnitude.currency!r}, "
            "<magnitude-account-dates-description-redacted>)"
        )


@runtime_checkable
class FinancialManualEntryMovementStore(Protocol):
    """Minimal append-only Movement persistence boundary used by the use case."""

    def create_movement(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialMovementDraft,
    ) -> FinancialMovementRecord: ...


class FinancialManualEntryService:
    """Persist manual income/expense intents through the canonical Movement store."""

    def __init__(self, store: FinancialManualEntryMovementStore) -> None:
        if not isinstance(store, FinancialManualEntryMovementStore):
            raise TypeError("store must implement FinancialManualEntryMovementStore")
        self._store = store

    def record(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialManualEntryDraft,
    ) -> FinancialMovementRecord:
        validate_financial_idempotency_key(idempotency_key)
        if not isinstance(draft, FinancialManualEntryDraft):
            raise TypeError("draft must be FinancialManualEntryDraft")

        return self._store.create_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=idempotency_key,
            draft=draft.to_movement_draft(),
        )


__all__ = [
    "FinancialManualEntryDraft",
    "FinancialManualEntryMovementStore",
    "FinancialManualEntryService",
    "FinancialManualEntryType",
]
