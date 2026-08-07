"""Server-side verification and persistence of a completed Pluggy Item."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, TypeAlias, TypeVar, runtime_checkable
from uuid import UUID

from meufinanceiro_banking_pluggy import (
    PluggyCapability,
    PluggyCapabilityAvailability,
    PluggyCapabilityEvidence,
    PluggyConnectionPhase,
    PluggyGatewayError,
    PluggyGatewayErrorCategory,
    PluggyGatewayHttpTransport,
    PluggyItemSnapshot,
    parse_connected_item,
)
from meufinanceiro_banking_pluggy.transport import PluggyApplicationCredentials
from meufinanceiro_persistence import (
    BankingConnectionRecord,
    BankingPersistenceError,
    CapabilitySnapshot,
    ConfigurationNotFoundError,
    ConnectionConflictError,
    EnabledProviderCredentials,
    ProviderNotEnabledError,
    StoredCapability,
    StoredCapabilitySource,
    StoredCapabilityState,
    StoredConnectionStatus,
)

_Result = TypeVar("_Result")
Clock: TypeAlias = Callable[[], datetime]

_PHASE_TO_STATUS = {
    PluggyConnectionPhase.CONNECTING: StoredConnectionStatus.PENDING_USER_ACTION,
    PluggyConnectionPhase.SYNCING: StoredConnectionStatus.SYNCING,
    PluggyConnectionPhase.AVAILABLE: StoredConnectionStatus.AVAILABLE,
    PluggyConnectionPhase.PARTIAL: StoredConnectionStatus.PARTIAL,
    PluggyConnectionPhase.USER_ACTION_REQUIRED: StoredConnectionStatus.PENDING_USER_ACTION,
    PluggyConnectionPhase.REAUTHENTICATION_REQUIRED: (
        StoredConnectionStatus.REAUTHENTICATION_REQUIRED
    ),
    PluggyConnectionPhase.TEMPORARILY_UNAVAILABLE: (
        StoredConnectionStatus.TEMPORARILY_UNAVAILABLE
    ),
    PluggyConnectionPhase.RATE_LIMITED: StoredConnectionStatus.RATE_LIMITED,
    PluggyConnectionPhase.DISCONNECTED: StoredConnectionStatus.DISCONNECTED,
    PluggyConnectionPhase.FAILED: StoredConnectionStatus.FAILED,
}

_CAPABILITY_TO_STORED = {
    PluggyCapability.IDENTITY: StoredCapability.IDENTITY,
    PluggyCapability.BANK_ACCOUNTS: StoredCapability.BANK_ACCOUNTS,
    PluggyCapability.CREDIT_ACCOUNTS: StoredCapability.CREDIT_ACCOUNTS,
    PluggyCapability.TRANSACTIONS: StoredCapability.TRANSACTIONS,
}

_AVAILABILITY_TO_STORED = {
    PluggyCapabilityAvailability.AVAILABLE: StoredCapabilityState.SUPPORTED,
    PluggyCapabilityAvailability.UNAVAILABLE: StoredCapabilityState.NOT_AVAILABLE,
    PluggyCapabilityAvailability.USER_ACTION_REQUIRED: (
        StoredCapabilityState.REQUIRES_USER_ACTION
    ),
    PluggyCapabilityAvailability.NOT_OBSERVED: StoredCapabilityState.NOT_OBSERVED,
    PluggyCapabilityAvailability.UNKNOWN: StoredCapabilityState.UNKNOWN,
}

_EVIDENCE_TO_STORED = {
    PluggyCapabilityEvidence.CONTRACT: StoredCapabilitySource.CONTRACT,
    PluggyCapabilityEvidence.OBSERVATION: StoredCapabilitySource.OBSERVATION,
    PluggyCapabilityEvidence.OPERATION: StoredCapabilitySource.OPERATION,
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PluggyConnectionRegistrationErrorCode(StrEnum):
    CONFIGURATION_REQUIRED = "CONFIGURATION_REQUIRED"
    PROVIDER_NOT_ENABLED = "PROVIDER_NOT_ENABLED"
    ITEM_NOT_ALLOWED = "ITEM_NOT_ALLOWED"
    ITEM_UNAVAILABLE = "ITEM_UNAVAILABLE"
    INVALID_PROVIDER_RESPONSE = "INVALID_PROVIDER_RESPONSE"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    CONNECTION_CONFLICT = "CONNECTION_CONFLICT"
    INTERNAL = "INTERNAL"


_ERROR_MESSAGES = {
    PluggyConnectionRegistrationErrorCode.CONFIGURATION_REQUIRED: (
        "banking provider configuration is required"
    ),
    PluggyConnectionRegistrationErrorCode.PROVIDER_NOT_ENABLED: (
        "banking provider must be enabled"
    ),
    PluggyConnectionRegistrationErrorCode.ITEM_NOT_ALLOWED: (
        "banking connection is not available for this residence"
    ),
    PluggyConnectionRegistrationErrorCode.ITEM_UNAVAILABLE: (
        "banking connection could not be verified"
    ),
    PluggyConnectionRegistrationErrorCode.INVALID_PROVIDER_RESPONSE: (
        "banking provider returned an invalid response"
    ),
    PluggyConnectionRegistrationErrorCode.TEMPORARILY_UNAVAILABLE: (
        "banking provider is temporarily unavailable"
    ),
    PluggyConnectionRegistrationErrorCode.CONNECTION_CONFLICT: (
        "banking connection is already assigned"
    ),
    PluggyConnectionRegistrationErrorCode.INTERNAL: (
        "banking connection could not be registered"
    ),
}


class PluggyConnectionRegistrationError(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: PluggyConnectionRegistrationErrorCode) -> None:
        if not isinstance(code, PluggyConnectionRegistrationErrorCode):
            raise TypeError("code must be PluggyConnectionRegistrationErrorCode")
        super().__init__(_ERROR_MESSAGES[code])
        self.code = code


@dataclass(frozen=True, slots=True)
class RegisteredPluggyConnection:
    connection_id: UUID
    status: StoredConnectionStatus
    requires_user_action: bool


@runtime_checkable
class RegistrationBankingStore(Protocol):
    def use_enabled_credentials(
        self,
        *,
        installation_id: UUID,
        provider: str,
        operation: Callable[[EnabledProviderCredentials], _Result],
    ) -> _Result: ...

    def register_connection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        provider: str,
        external_connection_id: str,
        status: StoredConnectionStatus,
        requires_user_action: bool,
        last_successful_sync_at: datetime | None = None,
        last_attempt_at: datetime | None = None,
        next_refresh_allowed_at: datetime | None = None,
        consent_expires_at: datetime | None = None,
        provider_reason_code: str | None = None,
        disconnected_at: datetime | None = None,
    ) -> BankingConnectionRecord: ...

    def replace_capabilities(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        snapshots: tuple[CapabilitySnapshot, ...],
    ) -> tuple[object, ...]: ...


@runtime_checkable
class ConnectedItemTransport(Protocol):
    def get_item(self, item_id: str) -> dict[str, object]: ...

    def close(self) -> None: ...


RegistrationTransportFactory: TypeAlias = Callable[
    [PluggyApplicationCredentials],
    ConnectedItemTransport,
]


def _default_transport_factory(
    credentials: PluggyApplicationCredentials,
) -> ConnectedItemTransport:
    return PluggyGatewayHttpTransport(credentials)


def _map_gateway_error(error: PluggyGatewayError) -> PluggyConnectionRegistrationError:
    if error.category is PluggyGatewayErrorCategory.AUTHORIZATION:
        code = PluggyConnectionRegistrationErrorCode.ITEM_NOT_ALLOWED
    elif error.category is PluggyGatewayErrorCategory.NOT_FOUND:
        code = PluggyConnectionRegistrationErrorCode.ITEM_UNAVAILABLE
    elif error.category in {
        PluggyGatewayErrorCategory.RATE_LIMITED,
        PluggyGatewayErrorCategory.TEMPORARILY_UNAVAILABLE,
    }:
        code = PluggyConnectionRegistrationErrorCode.TEMPORARILY_UNAVAILABLE
    elif error.category is PluggyGatewayErrorCategory.INTERNAL:
        code = PluggyConnectionRegistrationErrorCode.INVALID_PROVIDER_RESPONSE
    else:
        code = PluggyConnectionRegistrationErrorCode.ITEM_UNAVAILABLE
    return PluggyConnectionRegistrationError(code)


def _capability_snapshots(item: PluggyItemSnapshot) -> tuple[CapabilitySnapshot, ...]:
    return tuple(
        CapabilitySnapshot(
            capability=_CAPABILITY_TO_STORED[snapshot.capability],
            state=_AVAILABILITY_TO_STORED[snapshot.availability],
            source=_EVIDENCE_TO_STORED[snapshot.evidence],
            observed_at=snapshot.observed_at,
            provider_reason_code=snapshot.provider_reason_code,
        )
        for snapshot in item.capabilities
    )


class PluggyConnectionRegistrationService:
    """Verify Item ownership at the provider before any local persistence."""

    def __init__(
        self,
        store: RegistrationBankingStore,
        *,
        transport_factory: RegistrationTransportFactory = _default_transport_factory,
        clock: Clock = _utc_now,
    ) -> None:
        if not isinstance(store, RegistrationBankingStore):
            raise TypeError("store must satisfy RegistrationBankingStore")
        if not callable(transport_factory):
            raise TypeError("transport_factory must be callable")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._store = store
        self._transport_factory = transport_factory
        self._clock = clock

    def register(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        item_id: str,
    ) -> RegisteredPluggyConnection:
        if not isinstance(installation_id, UUID):
            raise TypeError("installation_id must be UUID")
        if not isinstance(residence_id, UUID):
            raise TypeError("residence_id must be UUID")
        if not isinstance(item_id, str):
            raise TypeError("item_id must be a string")
        normalized_item_id = item_id.strip()
        if (
            not normalized_item_id
            or len(normalized_item_id) > 512
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in normalized_item_id
            )
        ):
            raise ValueError("item_id is invalid")
        expected_client_user_id = f"residence:{residence_id}"

        def verify(credentials: EnabledProviderCredentials) -> PluggyItemSnapshot:
            if credentials.provider != "pluggy":
                raise PluggyConnectionRegistrationError(
                    PluggyConnectionRegistrationErrorCode.INTERNAL
                )
            transport: ConnectedItemTransport | None = None
            active_error: BaseException | None = None
            try:
                application_credentials = PluggyApplicationCredentials(
                    credentials.client_id,
                    credentials.client_secret,
                )
                transport = self._transport_factory(application_credentials)
                if not isinstance(transport, ConnectedItemTransport):
                    raise TypeError("transport factory returned an invalid object")
                payload = transport.get_item(normalized_item_id)
                return parse_connected_item(
                    payload,
                    expected_item_id=normalized_item_id,
                    expected_client_user_id=expected_client_user_id,
                    clock=self._clock,
                )
            except PluggyConnectionRegistrationError as error:
                active_error = error
                raise
            except PluggyGatewayError as error:
                active_error = error
                raise _map_gateway_error(error) from None
            except Exception as error:
                active_error = error
                raise PluggyConnectionRegistrationError(
                    PluggyConnectionRegistrationErrorCode.INTERNAL
                ) from None
            finally:
                if transport is not None:
                    try:
                        transport.close()
                    except Exception:
                        if active_error is None:
                            raise PluggyConnectionRegistrationError(
                                PluggyConnectionRegistrationErrorCode.INTERNAL
                            ) from None

        try:
            item = self._store.use_enabled_credentials(
                installation_id=installation_id,
                provider="pluggy",
                operation=verify,
            )
        except PluggyConnectionRegistrationError:
            raise
        except ConfigurationNotFoundError:
            raise PluggyConnectionRegistrationError(
                PluggyConnectionRegistrationErrorCode.CONFIGURATION_REQUIRED
            ) from None
        except ProviderNotEnabledError:
            raise PluggyConnectionRegistrationError(
                PluggyConnectionRegistrationErrorCode.PROVIDER_NOT_ENABLED
            ) from None
        except BankingPersistenceError:
            raise PluggyConnectionRegistrationError(
                PluggyConnectionRegistrationErrorCode.INTERNAL
            ) from None
        except Exception:
            raise PluggyConnectionRegistrationError(
                PluggyConnectionRegistrationErrorCode.INTERNAL
            ) from None

        status = _PHASE_TO_STATUS[item.phase]
        requires_user_action = status in {
            StoredConnectionStatus.PENDING_USER_ACTION,
            StoredConnectionStatus.REAUTHENTICATION_REQUIRED,
        }
        disconnected_at = self._clock() if status is StoredConnectionStatus.DISCONNECTED else None
        try:
            connection = self._store.register_connection(
                installation_id=installation_id,
                residence_id=residence_id,
                provider="pluggy",
                external_connection_id=item.item_id,
                status=status,
                requires_user_action=requires_user_action,
                last_successful_sync_at=item.last_successful_update_at,
                last_attempt_at=item.last_attempt_at,
                next_refresh_allowed_at=item.next_refresh_allowed_at,
                consent_expires_at=item.consent_expires_at,
                provider_reason_code=item.provider_reason_code,
                disconnected_at=disconnected_at,
            )
            self._store.replace_capabilities(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection.id,
                snapshots=_capability_snapshots(item),
            )
        except ConnectionConflictError:
            raise PluggyConnectionRegistrationError(
                PluggyConnectionRegistrationErrorCode.CONNECTION_CONFLICT
            ) from None
        except BankingPersistenceError:
            raise PluggyConnectionRegistrationError(
                PluggyConnectionRegistrationErrorCode.INTERNAL
            ) from None
        except Exception:
            raise PluggyConnectionRegistrationError(
                PluggyConnectionRegistrationErrorCode.INTERNAL
            ) from None

        return RegisteredPluggyConnection(
            connection_id=connection.id,
            status=connection.status,
            requires_user_action=connection.requires_user_action,
        )
