"""Application projection for consent lifecycle using only local banking facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from meufinanceiro_persistence import StoredConnectionStatus

from .consent_lifecycle import ConsentLifecycleEvaluator, ConsentLifecycleResult


class LocalConsentLifecycleError(RuntimeError):
    """Base sanitized error for local consent lifecycle projection."""


class ConsentConnectionNotFoundError(LocalConsentLifecycleError):
    """The requested local connection is absent or invisible to the actor."""


@dataclass(frozen=True, slots=True, repr=False)
class ConsentConnectionSnapshot:
    """Minimum actor-authorized local facts required by the lifecycle evaluator."""

    status: StoredConnectionStatus
    consent_expires_at: datetime | None

    def __post_init__(self) -> None:
        if not isinstance(self.status, StoredConnectionStatus):
            raise TypeError("status must be StoredConnectionStatus")
        if self.consent_expires_at is not None and (
            not isinstance(self.consent_expires_at, datetime)
            or self.consent_expires_at.tzinfo is None
            or self.consent_expires_at.utcoffset() is None
        ):
            raise ValueError("consent_expires_at must be timezone-aware")

    def __repr__(self) -> str:
        return "ConsentConnectionSnapshot(<local-consent-facts-redacted>)"


@runtime_checkable
class ConsentConnectionReader(Protocol):
    """Actor-aware reader that must fail closed before returning connection facts."""

    def read_consent_connection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        connection_id: UUID,
    ) -> ConsentConnectionSnapshot:
        """Return only consent facts after proving actor/residence access."""
        ...


class LocalConsentLifecycleService:
    """Evaluate one local connection without provider access or external identifiers."""

    def __init__(
        self,
        *,
        reader: ConsentConnectionReader,
        evaluator: ConsentLifecycleEvaluator,
    ) -> None:
        if not isinstance(reader, ConsentConnectionReader):
            raise TypeError("reader must satisfy ConsentConnectionReader")
        if not isinstance(evaluator, ConsentLifecycleEvaluator):
            raise TypeError("evaluator must be ConsentLifecycleEvaluator")
        self._reader = reader
        self._evaluator = evaluator

    def evaluate_connection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        connection_id: UUID,
    ) -> ConsentLifecycleResult:
        _require_uuid4(installation_id, "installation_id")
        _require_uuid4(residence_id, "residence_id")
        _require_uuid4(operator_id, "operator_id")
        _require_uuid4(connection_id, "connection_id")

        snapshot = self._reader.read_consent_connection(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            connection_id=connection_id,
        )
        if not isinstance(snapshot, ConsentConnectionSnapshot):
            raise TypeError("reader returned an invalid consent connection snapshot")

        return self._evaluator.classify(
            connection_status=snapshot.status,
            consent_expires_at=snapshot.consent_expires_at,
        )


def _require_uuid4(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID) or value.version != 4:
        raise ValueError(f"{field_name} must be UUIDv4")


__all__ = [
    "ConsentConnectionNotFoundError",
    "ConsentConnectionReader",
    "ConsentConnectionSnapshot",
    "LocalConsentLifecycleError",
    "LocalConsentLifecycleService",
]
