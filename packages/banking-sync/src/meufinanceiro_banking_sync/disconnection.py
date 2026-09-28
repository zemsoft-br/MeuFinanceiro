"""Provider-neutral explicit banking connection disconnection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from meufinanceiro_banking import (
    BankingProvider,
    BankingProviderError,
    ConnectionStatus,
    ProviderErrorCategory,
)
from meufinanceiro_persistence import (
    BankingConnectionRecord,
    BankingPersistenceError,
    ConnectionNotFoundError,
    StoredConnectionStatus,
    SyncConflictError,
)


class ConnectionDisconnectionErrorCode(StrEnum):
    """Sanitized application-level failure categories."""

    CONNECTION_NOT_FOUND = "CONNECTION_NOT_FOUND"
    CONNECTION_NOT_AVAILABLE = "CONNECTION_NOT_AVAILABLE"
    CONNECTION_BUSY = "CONNECTION_BUSY"
    PROVIDER_UNSUPPORTED = "PROVIDER_UNSUPPORTED"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    INTERNAL = "INTERNAL"


_ERROR_MESSAGES = {
    ConnectionDisconnectionErrorCode.CONNECTION_NOT_FOUND: (
        "banking connection was not found"
    ),
    ConnectionDisconnectionErrorCode.CONNECTION_NOT_AVAILABLE: (
        "banking connection is not available for this provider"
    ),
    ConnectionDisconnectionErrorCode.CONNECTION_BUSY: (
        "banking connection has an active synchronization"
    ),
    ConnectionDisconnectionErrorCode.PROVIDER_UNSUPPORTED: (
        "banking provider does not support disconnection"
    ),
    ConnectionDisconnectionErrorCode.PROVIDER_REJECTED: (
        "banking provider rejected disconnection"
    ),
    ConnectionDisconnectionErrorCode.TEMPORARILY_UNAVAILABLE: (
        "banking provider is temporarily unavailable"
    ),
    ConnectionDisconnectionErrorCode.INTERNAL: (
        "banking connection disconnection failed"
    ),
}


class ConnectionDisconnectionError(RuntimeError):
    """Sanitized failure that never exposes provider or external identifiers."""

    __slots__ = ("code",)

    def __init__(self, code: ConnectionDisconnectionErrorCode) -> None:
        if not isinstance(code, ConnectionDisconnectionErrorCode):
            raise TypeError("code must be ConnectionDisconnectionErrorCode")
        super().__init__(_ERROR_MESSAGES[code])
        self.code = code


class ConnectionDisconnectionOutcome(StrEnum):
    DISCONNECTED = "disconnected"
    ALREADY_DISCONNECTED = "already_disconnected"
    RECOVERED = "recovered"


@dataclass(frozen=True, slots=True, repr=False)
class ConnectionDisconnectionResult:
    outcome: ConnectionDisconnectionOutcome

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, ConnectionDisconnectionOutcome):
            raise TypeError("outcome must be ConnectionDisconnectionOutcome")

    def __repr__(self) -> str:
        return f"ConnectionDisconnectionResult(outcome={self.outcome.value!r})"


@runtime_checkable
class ConnectionDisconnectionStore(Protocol):
    """Minimal residence-scoped persistence boundary for disconnection."""

    def get_connection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
    ) -> BankingConnectionRecord: ...

    def execute_connection_disconnection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        operation: Callable[[], None],
    ) -> bool: ...


class _ProviderOperationFailure(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: ConnectionDisconnectionErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


def _provider_error_code(
    category: ProviderErrorCategory,
) -> ConnectionDisconnectionErrorCode:
    if category is ProviderErrorCategory.UNSUPPORTED:
        return ConnectionDisconnectionErrorCode.PROVIDER_UNSUPPORTED

    if category in {
        ProviderErrorCategory.RATE_LIMITED,
        ProviderErrorCategory.TEMPORARILY_UNAVAILABLE,
    }:
        return ConnectionDisconnectionErrorCode.TEMPORARILY_UNAVAILABLE

    if category is ProviderErrorCategory.INTERNAL:
        return ConnectionDisconnectionErrorCode.INTERNAL

    return ConnectionDisconnectionErrorCode.PROVIDER_REJECTED


def _require_uuid(value: UUID, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")
    return value


class BankingConnectionDisconnectionService:
    """Disconnect one local connection without deleting retained history."""

    def __init__(
        self,
        provider: BankingProvider,
        store: ConnectionDisconnectionStore,
    ) -> None:
        if not isinstance(provider, BankingProvider):
            raise TypeError("provider must satisfy BankingProvider")
        if not isinstance(store, ConnectionDisconnectionStore):
            raise TypeError("store must satisfy ConnectionDisconnectionStore")

        self._provider = provider
        self._store = store

    def disconnect(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        connection_id: UUID,
    ) -> ConnectionDisconnectionResult:
        _require_uuid(installation_id, "installation_id")
        _require_uuid(residence_id, "residence_id")
        _require_uuid(operator_id, "operator_id")
        _require_uuid(connection_id, "connection_id")

        connection = self._load_connection(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
        )

        if connection.status is StoredConnectionStatus.DISCONNECTED:
            return ConnectionDisconnectionResult(
                ConnectionDisconnectionOutcome.ALREADY_DISCONNECTED
            )

        try:
            provider_name = self._provider.provider_name
        except Exception:
            raise ConnectionDisconnectionError(
                ConnectionDisconnectionErrorCode.INTERNAL
            ) from None

        if connection.provider != provider_name:
            raise ConnectionDisconnectionError(
                ConnectionDisconnectionErrorCode.CONNECTION_NOT_AVAILABLE
            )

        provider_already_disconnected = False

        def provider_operation() -> None:
            nonlocal provider_already_disconnected

            try:
                provider_state = self._provider.get_connection(
                    connection.external_connection_id
                )

                if provider_state.status is ConnectionStatus.DISCONNECTED:
                    provider_already_disconnected = True
                    return

                self._provider.disconnect(
                    connection.external_connection_id,
                    str(operator_id),
                )
            except BankingProviderError as error:
                raise _ProviderOperationFailure(
                    _provider_error_code(error.category)
                ) from None
            except Exception:
                raise _ProviderOperationFailure(
                    ConnectionDisconnectionErrorCode.INTERNAL
                ) from None

        try:
            executed = self._store.execute_connection_disconnection(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                operation=provider_operation,
            )
        except _ProviderOperationFailure as error:
            raise ConnectionDisconnectionError(error.code) from None
        except ConnectionNotFoundError:
            raise ConnectionDisconnectionError(
                ConnectionDisconnectionErrorCode.CONNECTION_NOT_FOUND
            ) from None
        except SyncConflictError:
            raise ConnectionDisconnectionError(
                ConnectionDisconnectionErrorCode.CONNECTION_BUSY
            ) from None
        except BankingPersistenceError:
            raise ConnectionDisconnectionError(
                ConnectionDisconnectionErrorCode.INTERNAL
            ) from None
        except Exception:
            raise ConnectionDisconnectionError(
                ConnectionDisconnectionErrorCode.INTERNAL
            ) from None

        if not executed:
            return ConnectionDisconnectionResult(
                ConnectionDisconnectionOutcome.ALREADY_DISCONNECTED
            )

        if provider_already_disconnected:
            return ConnectionDisconnectionResult(
                ConnectionDisconnectionOutcome.RECOVERED
            )

        return ConnectionDisconnectionResult(
            ConnectionDisconnectionOutcome.DISCONNECTED
        )

    def _load_connection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
    ) -> BankingConnectionRecord:
        try:
            return self._store.get_connection(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
            )
        except ConnectionNotFoundError:
            raise ConnectionDisconnectionError(
                ConnectionDisconnectionErrorCode.CONNECTION_NOT_FOUND
            ) from None
        except BankingPersistenceError:
            raise ConnectionDisconnectionError(
                ConnectionDisconnectionErrorCode.INTERNAL
            ) from None
        except Exception:
            raise ConnectionDisconnectionError(
                ConnectionDisconnectionErrorCode.INTERNAL
            ) from None
