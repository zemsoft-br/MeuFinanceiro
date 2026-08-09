"""Immutable redacted contracts for transaction-observation reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from meufinanceiro_persistence.banking_models import require_aware
from meufinanceiro_persistence.banking_observation_models import (
    StoredTransactionObservationStatus,
)


class ReconciledTransactionIdentityKind(StrEnum):
    PROVIDER_ID = "PROVIDER_ID"
    FINGERPRINT = "FINGERPRINT"


class TransactionReconciliationError(RuntimeError):
    """Sanitized reconciliation failure without provider/financial material."""


class TransactionReconciliationConflictError(TransactionReconciliationError):
    """Fail-closed deterministic identity or temporal conflict."""


@dataclass(frozen=True, slots=True, repr=False)
class ReconciledTransactionRecord:
    id: UUID
    residence_id: UUID
    connection_id: UUID
    external_account_record_id: UUID
    identity_kind: ReconciledTransactionIdentityKind
    identity_digest: str
    status: StoredTransactionObservationStatus
    source_observation_id: UUID
    source_observed_at: datetime
    first_reconciled_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.identity_kind, ReconciledTransactionIdentityKind):
            raise TypeError("identity_kind must be ReconciledTransactionIdentityKind")
        if len(self.identity_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.identity_digest
        ):
            raise ValueError("identity_digest must be a lowercase sha256 digest")
        if not isinstance(self.status, StoredTransactionObservationStatus):
            raise TypeError("status must be StoredTransactionObservationStatus")
        require_aware(self.source_observed_at, "source_observed_at")
        require_aware(self.first_reconciled_at, "first_reconciled_at")
        require_aware(self.updated_at, "updated_at")

    def __repr__(self) -> str:
        return (
            "ReconciledTransactionRecord("
            f"identity_kind={self.identity_kind.value!r}, "
            f"status={self.status.value!r}, <identity-and-scope-redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class TransactionReconciliationResult:
    observations_seen: int
    identities_created: int
    identities_updated: int
    identities_unchanged: int
    has_more: bool

    def __post_init__(self) -> None:
        for field_name in (
            "observations_seen",
            "identities_created",
            "identities_updated",
            "identities_unchanged",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if (
            self.identities_created
            + self.identities_updated
            + self.identities_unchanged
            != self.observations_seen
        ):
            raise ValueError("reconciliation counts must add up to observations_seen")
        if not isinstance(self.has_more, bool):
            raise TypeError("has_more must be bool")

    def __repr__(self) -> str:
        return (
            "TransactionReconciliationResult("
            f"observations_seen={self.observations_seen}, "
            f"identities_created={self.identities_created}, "
            f"identities_updated={self.identities_updated}, "
            f"identities_unchanged={self.identities_unchanged}, "
            f"has_more={self.has_more})"
        )


__all__ = [
    "ReconciledTransactionIdentityKind",
    "ReconciledTransactionRecord",
    "TransactionReconciliationConflictError",
    "TransactionReconciliationError",
    "TransactionReconciliationResult",
]
