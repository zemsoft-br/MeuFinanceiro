"""Provider-neutral contracts for explicit banking-to-ledger review decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from meufinanceiro_persistence.banking_models import require_aware
from meufinanceiro_persistence.banking_observation_models import (
    StoredTransactionObservationStatus,
)


class BankingLedgerReviewDecision(StrEnum):
    IMPORT_AS_INCOME = "IMPORT_AS_INCOME"
    IMPORT_AS_EXPENSE = "IMPORT_AS_EXPENSE"
    LINK_EXISTING_MOVEMENT = "LINK_EXISTING_MOVEMENT"
    IGNORE = "IGNORE"


class BankingLedgerReviewError(RuntimeError):
    """Sanitized review failure without provider-specific identity material."""


class BankingLedgerReviewAccessError(BankingLedgerReviewError):
    """Actor has no active membership in the requested residence."""


class BankingLedgerReviewNotFoundError(BankingLedgerReviewError):
    """The reconciled transaction or requested target was not visible."""


class BankingLedgerReviewConflictError(BankingLedgerReviewError):
    """The reviewed source snapshot or an idempotent decision conflicts."""


class BankingLedgerReviewNotEligibleError(BankingLedgerReviewError):
    """The reconciled state cannot be promoted by the requested decision."""


class BankingLedgerReviewPersistenceError(BankingLedgerReviewError):
    """Sanitized persistence failure for the review bridge."""


@dataclass(frozen=True, slots=True, repr=False)
class BankingLedgerReviewCandidate:
    reconciled_transaction_id: UUID
    external_account_record_id: UUID
    status: StoredTransactionObservationStatus
    effective_date: date
    amount: Decimal
    currency: str
    description: str | None
    source_observation_id: UUID
    source_observation_updated_at: datetime

    def __post_init__(self) -> None:
        _require_uuid(self.reconciled_transaction_id, "reconciled_transaction_id")
        _require_uuid(self.external_account_record_id, "external_account_record_id")
        if not isinstance(self.status, StoredTransactionObservationStatus):
            raise TypeError("status must be StoredTransactionObservationStatus")
        if not isinstance(self.effective_date, date) or isinstance(
            self.effective_date, datetime
        ):
            raise TypeError("effective_date must be date")
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite():
            raise TypeError("amount must be a finite Decimal")
        if not isinstance(self.currency, str) or len(self.currency) != 3:
            raise ValueError("currency must be a three-letter code")
        if any(character < "A" or character > "Z" for character in self.currency):
            raise ValueError("currency must be uppercase ASCII letters")
        if self.description is not None:
            if not isinstance(self.description, str):
                raise TypeError("description must be str or None")
            if not self.description or self.description != self.description.strip():
                raise ValueError("description must be normalized when present")
        _require_uuid(self.source_observation_id, "source_observation_id")
        require_aware(
            self.source_observation_updated_at,
            "source_observation_updated_at",
        )

    def __repr__(self) -> str:
        return (
            "BankingLedgerReviewCandidate("
            f"status={self.status.value!r}, currency={self.currency!r}, "
            "<financial-and-scope-material-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class BankingLedgerReviewDraft:
    source_observation_id: UUID
    source_observation_updated_at: datetime
    decision: BankingLedgerReviewDecision
    financial_account_id: UUID | None = None
    movement_id: UUID | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.source_observation_id, "source_observation_id")
        require_aware(
            self.source_observation_updated_at,
            "source_observation_updated_at",
        )
        if not isinstance(self.decision, BankingLedgerReviewDecision):
            raise TypeError("decision must be BankingLedgerReviewDecision")

        if self.decision in {
            BankingLedgerReviewDecision.IMPORT_AS_INCOME,
            BankingLedgerReviewDecision.IMPORT_AS_EXPENSE,
        }:
            if self.financial_account_id is None:
                raise ValueError("import decision requires financial_account_id")
            _require_uuid(self.financial_account_id, "financial_account_id")
            if self.movement_id is not None:
                raise ValueError("import decision must not provide movement_id")
            return

        if self.decision is BankingLedgerReviewDecision.LINK_EXISTING_MOVEMENT:
            if self.financial_account_id is not None:
                raise ValueError("link decision derives financial_account_id")
            if self.movement_id is None:
                raise ValueError("link decision requires movement_id")
            _require_uuid(self.movement_id, "movement_id")
            return

        if self.financial_account_id is not None or self.movement_id is not None:
            raise ValueError("ignore decision must not target financial state")

    def __repr__(self) -> str:
        return (
            "BankingLedgerReviewDraft("
            f"decision={self.decision.value!r}, <targets-and-snapshot-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class BankingLedgerReviewRecord:
    id: UUID
    reconciled_transaction_id: UUID
    source_observation_id: UUID
    source_observation_updated_at: datetime
    decision: BankingLedgerReviewDecision
    financial_account_id: UUID | None
    movement_id: UUID | None
    decided_by_operator_id: UUID
    decided_at: datetime

    def __post_init__(self) -> None:
        _require_uuid(self.id, "id")
        _require_uuid(self.reconciled_transaction_id, "reconciled_transaction_id")
        _require_uuid(self.source_observation_id, "source_observation_id")
        require_aware(
            self.source_observation_updated_at,
            "source_observation_updated_at",
        )
        if not isinstance(self.decision, BankingLedgerReviewDecision):
            raise TypeError("decision must be BankingLedgerReviewDecision")
        if self.financial_account_id is not None:
            _require_uuid(self.financial_account_id, "financial_account_id")
        if self.movement_id is not None:
            _require_uuid(self.movement_id, "movement_id")
        _require_uuid(self.decided_by_operator_id, "decided_by_operator_id")
        require_aware(self.decided_at, "decided_at")

    def __repr__(self) -> str:
        return (
            "BankingLedgerReviewRecord("
            f"decision={self.decision.value!r}, "
            f"has_movement={self.movement_id is not None}, "
            "<identity-and-scope-redacted>)"
        )


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


__all__ = [
    "BankingLedgerReviewAccessError",
    "BankingLedgerReviewCandidate",
    "BankingLedgerReviewConflictError",
    "BankingLedgerReviewDecision",
    "BankingLedgerReviewDraft",
    "BankingLedgerReviewError",
    "BankingLedgerReviewNotEligibleError",
    "BankingLedgerReviewNotFoundError",
    "BankingLedgerReviewPersistenceError",
    "BankingLedgerReviewRecord",
]
