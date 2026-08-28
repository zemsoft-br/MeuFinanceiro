"""Application projection for consent lifecycle using only local banking facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from meufinanceiro_persistence import (
    BankingConsentConnectionSnapshot,
    BankingPersistenceError,
    ConnectionNotFoundError,
    StoredConnectionStatus,
)

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


@runtime_checkable
class ConsentConnectionFactStore(Protocol):
    """Persistence boundary that exposes no provider or external identifier material."""

    def get_consent_connection_snapshot(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        connection_id: UUID,
    ) -> BankingConsentConnectionSnapshot:
        """Return the minimal persisted consent facts for an authorized actor."""
        ...


class PersistenceConsentConnectionReader:
    """Translate sanitized persistence facts into the application reader contract."""

    def __init__(self, store: ConsentConnectionFactStore) -> None:
        if not isinstance(store, ConsentConnectionFactStore):
            raise TypeError("store must satisfy ConsentConnectionFactStore")
        self._store = store

    def read_consent_connection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        connection_id: UUID,
    ) -> ConsentConnectionSnapshot:
        try:
            persisted = self._store.get_consent_connection_snapshot(
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=operator_id,
                connection_id=connection_id,
            )
        except ConnectionNotFoundError:
            raise ConsentConnectionNotFoundError(
                "local banking connection was not found"
            ) from None
        except BankingPersistenceError:
            raise LocalConsentLifecycleError(
                "local banking consent facts could not be read"
            ) from None

        if not isinstance(persisted, BankingConsentConnectionSnapshot):
            raise TypeError("store returned invalid banking consent facts")
        return ConsentConnectionSnapshot(
            status=persisted.status,
            consent_expires_at=persisted.consent_expires_at,
        )


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
    "ConsentConnectionFactStore",
    "ConsentConnectionNotFoundError",
    "ConsentConnectionReader",
    "ConsentConnectionSnapshot",
    "LocalConsentLifecycleError",
    "LocalConsentLifecycleService",
    "PersistenceConsentConnectionReader",
]
