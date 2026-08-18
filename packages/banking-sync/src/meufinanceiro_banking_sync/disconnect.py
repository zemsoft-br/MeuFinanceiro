"""Provider-neutral explicit connection disconnection orchestration."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from meufinanceiro_banking import (
    BankingProvider,
    BankingProviderError,
    ConnectionState,
    ConnectionStatus,
)
from meufinanceiro_persistence import (
    BankingConnectionRecord,
    BankingPersistenceError,
    ConnectionConflictError,
    ConnectionNotFoundError,
    StoredConnectionStatus,
)


class BankingDisconnectErrorCode(StrEnum):
    NOT_FOUND = "not_found"
    BUSY = "busy"
    PROVIDER_MISMATCH = "provider_mismatch"
    PROVIDER_REJECTED = "provider_rejected"
    LOCAL_FINALIZATION_PENDING = "local_finalization_pending"
    INTERNAL = "internal"


class BankingDisconnectExecutionError(RuntimeError):
    """Sanitized disconnect failure without external IDs or provider payloads."""

    __slots__ = ("code",)

    def __init__(self, code: BankingDisconnectErrorCode) -> None:
        super().__init__(f"banking disconnect failed: {code.value}")
        self.code = code


@dataclass(frozen=True, slots=True, repr=False)
class BankingDisconnectResult:
    connection_id: UUID
    status: StoredConnectionStatus
    provider_mutation_performed: bool
    recovered_from_provider_state: bool

    def __post_init__(self) -> None:
        if not isinstance(self.connection_id, UUID):
            raise TypeError("connection_id must be UUID")
        if self.status is not StoredConnectionStatus.DISCONNECTED:
            raise ValueError("disconnect result must be DISCONNECTED")
        if self.provider_mutation_performed and self.recovered_from_provider_state:
            raise ValueError("disconnect result recovery flags are inconsistent")

    def __repr__(self) -> str:
        return (
            "BankingDisconnectResult("
            f"status={self.status.value!r}, "
            f"provider_mutation_performed={self.provider_mutation_performed!r}, "
            f"recovered_from_provider_state={self.recovered_from_provider_state!r}, "
            "<connection-id-redacted>)"
        )


class ConnectionDisconnectionStore(Protocol):
    def connection_disconnection_transaction(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        connection_id: UUID,
    ) -> AbstractContextManager[BankingConnectionRecord]: ...


class BankingConnectionDisconnectionService:
    """Disconnect one local banking connection with recoverable provider ordering."""

    def __init__(
        self,
        *,
        store: ConnectionDisconnectionStore,
        provider: BankingProvider,
    ) -> None:
        self._store = store
        self._provider = provider

    def disconnect_connection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        connection_id: UUID,
    ) -> BankingDisconnectResult:
        for field_name, value in (
            ("installation_id", installation_id),
            ("residence_id", residence_id),
            ("operator_id", operator_id),
            ("connection_id", connection_id),
        ):
            if not isinstance(value, UUID):
                raise TypeError(f"{field_name} must be UUID")

        provider_mutation_performed = False
        recovered_from_provider_state = False
        try:
            transaction = self._store.connection_disconnection_transaction(
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=operator_id,
                connection_id=connection_id,
            )
            with transaction as local:
                if local.status is StoredConnectionStatus.DISCONNECTED:
                    return _result(
                        connection_id=connection_id,
                        provider_mutation_performed=False,
                        recovered_from_provider_state=False,
                    )

                if self._provider.provider_name != local.provider:
                    raise BankingDisconnectExecutionError(
                        BankingDisconnectErrorCode.PROVIDER_MISMATCH
                    )

                remote = self._observe_remote(local.external_connection_id)
                if remote.external_connection_id != local.external_connection_id:
                    raise BankingDisconnectExecutionError(
                        BankingDisconnectErrorCode.PROVIDER_MISMATCH
                    )

                if remote.status is ConnectionStatus.DISCONNECTED:
                    recovered_from_provider_state = True
                else:
                    self._disconnect_remote(
                        external_connection_id=local.external_connection_id,
                        actor_id=str(operator_id),
                    )
                    provider_mutation_performed = True

            return _result(
                connection_id=connection_id,
                provider_mutation_performed=provider_mutation_performed,
                recovered_from_provider_state=recovered_from_provider_state,
            )
        except BankingDisconnectExecutionError:
            raise
        except ConnectionNotFoundError:
            raise BankingDisconnectExecutionError(
                BankingDisconnectErrorCode.NOT_FOUND
            ) from None
        except ConnectionConflictError:
            raise BankingDisconnectExecutionError(
                BankingDisconnectErrorCode.BUSY
            ) from None
        except BankingPersistenceError:
            code = (
                BankingDisconnectErrorCode.LOCAL_FINALIZATION_PENDING
                if provider_mutation_performed or recovered_from_provider_state
                else BankingDisconnectErrorCode.INTERNAL
            )
            raise BankingDisconnectExecutionError(code) from None

    def _observe_remote(self, external_connection_id: str) -> ConnectionState:
        try:
            return self._provider.get_connection(external_connection_id)
        except BankingProviderError:
            raise BankingDisconnectExecutionError(
                BankingDisconnectErrorCode.PROVIDER_REJECTED
            ) from None
        except Exception:
            raise BankingDisconnectExecutionError(
                BankingDisconnectErrorCode.INTERNAL
            ) from None

    def _disconnect_remote(
        self,
        *,
        external_connection_id: str,
        actor_id: str,
    ) -> None:
        try:
            self._provider.disconnect(external_connection_id, actor_id)
        except BankingProviderError:
            raise BankingDisconnectExecutionError(
                BankingDisconnectErrorCode.PROVIDER_REJECTED
            ) from None
        except Exception:
            raise BankingDisconnectExecutionError(
                BankingDisconnectErrorCode.INTERNAL
            ) from None


def _result(
    *,
    connection_id: UUID,
    provider_mutation_performed: bool,
    recovered_from_provider_state: bool,
) -> BankingDisconnectResult:
    return BankingDisconnectResult(
        connection_id=connection_id,
        status=StoredConnectionStatus.DISCONNECTED,
        provider_mutation_performed=provider_mutation_performed,
        recovered_from_provider_state=recovered_from_provider_state,
    )


__all__ = [
    "BankingConnectionDisconnectionService",
    "BankingDisconnectErrorCode",
    "BankingDisconnectExecutionError",
    "BankingDisconnectResult",
    "ConnectionDisconnectionStore",
]
