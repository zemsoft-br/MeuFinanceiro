"""Residence-scoped Pluggy reauthentication token issuance."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypeAlias, TypeVar, runtime_checkable
from uuid import UUID

from meufinanceiro_banking_pluggy import (
    PluggyConnectTokenHttpTransport,
    PluggyGatewayError,
    PluggyGatewayErrorCategory,
    parse_connected_item,
)
from meufinanceiro_banking_pluggy.transport import (
    JsonObject,
    PluggyApplicationCredentials,
    PluggyTransportError,
    PluggyTransportErrorCategory,
)
from meufinanceiro_persistence import (
    BankingConnectionRecord,
    BankingPersistenceError,
    ConfigurationNotFoundError,
    ConnectionNotFoundError,
    EnabledProviderCredentials,
    ProviderNotEnabledError,
    StoredConnectionStatus,
)

_Result = TypeVar("_Result")
_MAX_TOKEN_LENGTH = 4096
_MAX_ITEM_ID_LENGTH = 512


class PluggyReauthenticationErrorCode(StrEnum):
    CONNECTION_NOT_FOUND = "CONNECTION_NOT_FOUND"
    CONNECTION_NOT_AVAILABLE = "CONNECTION_NOT_AVAILABLE"
    CONNECTION_NOT_ALLOWED = "CONNECTION_NOT_ALLOWED"
    CONFIGURATION_REQUIRED = "CONFIGURATION_REQUIRED"
    PROVIDER_NOT_ENABLED = "PROVIDER_NOT_ENABLED"
    ITEM_UNAVAILABLE = "ITEM_UNAVAILABLE"
    INVALID_PROVIDER_RESPONSE = "INVALID_PROVIDER_RESPONSE"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    INTERNAL = "INTERNAL"


_ERROR_MESSAGES = {
    PluggyReauthenticationErrorCode.CONNECTION_NOT_FOUND: (
        "banking connection was not found"
    ),
    PluggyReauthenticationErrorCode.CONNECTION_NOT_AVAILABLE: (
        "banking connection cannot be reauthenticated"
    ),
    PluggyReauthenticationErrorCode.CONNECTION_NOT_ALLOWED: (
        "banking connection is not available for this residence"
    ),
    PluggyReauthenticationErrorCode.CONFIGURATION_REQUIRED: (
        "banking provider configuration is required"
    ),
    PluggyReauthenticationErrorCode.PROVIDER_NOT_ENABLED: (
        "banking provider must be enabled"
    ),
    PluggyReauthenticationErrorCode.ITEM_UNAVAILABLE: (
        "banking connection could not be verified"
    ),
    PluggyReauthenticationErrorCode.INVALID_PROVIDER_RESPONSE: (
        "banking provider returned an invalid response"
    ),
    PluggyReauthenticationErrorCode.PROVIDER_REJECTED: (
        "banking provider rejected reauthentication"
    ),
    PluggyReauthenticationErrorCode.TEMPORARILY_UNAVAILABLE: (
        "banking provider is temporarily unavailable"
    ),
    PluggyReauthenticationErrorCode.INTERNAL: (
        "banking reauthentication is unavailable"
    ),
}


class PluggyReauthenticationError(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: PluggyReauthenticationErrorCode) -> None:
        if not isinstance(code, PluggyReauthenticationErrorCode):
            raise TypeError("code must be PluggyReauthenticationErrorCode")
        super().__init__(_ERROR_MESSAGES[code])
        self.code = code


@dataclass(frozen=True, slots=True, repr=False)
class IssuedPluggyReauthenticationToken:
    access_token: str
    item_id: str

    def __post_init__(self) -> None:
        _validate_secret(self.access_token, "access_token", _MAX_TOKEN_LENGTH)
        _validate_secret(self.item_id, "item_id", _MAX_ITEM_ID_LENGTH)

    def __repr__(self) -> str:
        return "IssuedPluggyReauthenticationToken(<redacted>)"


@runtime_checkable
class ReauthenticationBankingStore(Protocol):
    def get_connection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
    ) -> BankingConnectionRecord: ...

    def use_enabled_credentials(
        self,
        *,
        installation_id: UUID,
        provider: str,
        operation: Callable[[EnabledProviderCredentials], _Result],
    ) -> _Result: ...


@runtime_checkable
class ReauthenticationTransport(Protocol):
    def get_item(self, item_id: str) -> JsonObject: ...

    def create_update_connect_token(self, *, item_id: str) -> str: ...

    def close(self) -> None: ...


ReauthenticationTransportFactory: TypeAlias = Callable[
    [PluggyApplicationCredentials],
    ReauthenticationTransport,
]


def _default_transport_factory(
    credentials: PluggyApplicationCredentials,
) -> ReauthenticationTransport:
    return PluggyConnectTokenHttpTransport(credentials)


def _validate_secret(value: str, field_name: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value != value.strip() or len(value) > max_length:
        raise ValueError(f"{field_name} is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field_name} contains control characters")
    return value


def _map_transport_error(error: PluggyTransportError) -> PluggyReauthenticationError:
    if error.category is PluggyTransportErrorCategory.NOT_FOUND:
        code = PluggyReauthenticationErrorCode.ITEM_UNAVAILABLE
    elif error.category in {
        PluggyTransportErrorCategory.RATE_LIMITED,
        PluggyTransportErrorCategory.TEMPORARILY_UNAVAILABLE,
    }:
        code = PluggyReauthenticationErrorCode.TEMPORARILY_UNAVAILABLE
    elif error.category is PluggyTransportErrorCategory.INVALID_RESPONSE:
        code = PluggyReauthenticationErrorCode.INVALID_PROVIDER_RESPONSE
    elif error.category in {
        PluggyTransportErrorCategory.AUTHENTICATION,
        PluggyTransportErrorCategory.AUTHORIZATION,
        PluggyTransportErrorCategory.INVALID_REQUEST,
    }:
        code = PluggyReauthenticationErrorCode.PROVIDER_REJECTED
    else:
        code = PluggyReauthenticationErrorCode.INTERNAL
    return PluggyReauthenticationError(code)


def _map_gateway_error(error: PluggyGatewayError) -> PluggyReauthenticationError:
    if error.category is PluggyGatewayErrorCategory.AUTHORIZATION:
        code = PluggyReauthenticationErrorCode.CONNECTION_NOT_ALLOWED
    elif error.category is PluggyGatewayErrorCategory.NOT_FOUND:
        code = PluggyReauthenticationErrorCode.ITEM_UNAVAILABLE
    elif error.category in {
        PluggyGatewayErrorCategory.RATE_LIMITED,
        PluggyGatewayErrorCategory.TEMPORARILY_UNAVAILABLE,
    }:
        code = PluggyReauthenticationErrorCode.TEMPORARILY_UNAVAILABLE
    elif error.category is PluggyGatewayErrorCategory.INTERNAL:
        code = PluggyReauthenticationErrorCode.INVALID_PROVIDER_RESPONSE
    else:
        code = PluggyReauthenticationErrorCode.PROVIDER_REJECTED
    return PluggyReauthenticationError(code)


class PluggyReauthenticationTokenService:
    """Verify one local connection before issuing its update-mode Connect Token."""

    def __init__(
        self,
        store: ReauthenticationBankingStore,
        *,
        transport_factory: ReauthenticationTransportFactory = (
            _default_transport_factory
        ),
    ) -> None:
        if not isinstance(store, ReauthenticationBankingStore):
            raise TypeError("store must satisfy ReauthenticationBankingStore")
        if not callable(transport_factory):
            raise TypeError("transport_factory must be callable")
        self._store = store
        self._transport_factory = transport_factory

    def issue(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
    ) -> IssuedPluggyReauthenticationToken:
        for field_name, value in (
            ("installation_id", installation_id),
            ("residence_id", residence_id),
            ("connection_id", connection_id),
        ):
            if not isinstance(value, UUID):
                raise TypeError(f"{field_name} must be UUID")

        connection = self._load_connection(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
        )
        expected_client_user_id = f"residence:{residence_id}"

        def verify_and_issue(
            credentials: EnabledProviderCredentials,
        ) -> IssuedPluggyReauthenticationToken:
            if credentials.provider != "pluggy":
                raise PluggyReauthenticationError(
                    PluggyReauthenticationErrorCode.INTERNAL
                )
            transport: ReauthenticationTransport | None = None
            active_error: BaseException | None = None
            try:
                application_credentials = PluggyApplicationCredentials(
                    credentials.client_id,
                    credentials.client_secret,
                )
                transport = self._transport_factory(application_credentials)
                if not isinstance(transport, ReauthenticationTransport):
                    raise TypeError("transport factory returned an invalid object")
                payload = transport.get_item(connection.external_connection_id)
                item = parse_connected_item(
                    payload,
                    expected_item_id=connection.external_connection_id,
                    expected_client_user_id=expected_client_user_id,
                )
                token = transport.create_update_connect_token(item_id=item.item_id)
                try:
                    return IssuedPluggyReauthenticationToken(
                        access_token=token,
                        item_id=item.item_id,
                    )
                except (TypeError, ValueError):
                    raise PluggyReauthenticationError(
                        PluggyReauthenticationErrorCode.INVALID_PROVIDER_RESPONSE
                    ) from None
            except PluggyReauthenticationError as error:
                active_error = error
                raise
            except PluggyTransportError as error:
                active_error = error
                raise _map_transport_error(error) from None
            except PluggyGatewayError as error:
                active_error = error
                raise _map_gateway_error(error) from None
            except Exception as error:
                active_error = error
                raise PluggyReauthenticationError(
                    PluggyReauthenticationErrorCode.INTERNAL
                ) from None
            finally:
                if transport is not None:
                    try:
                        transport.close()
                    except Exception:
                        if active_error is None:
                            raise PluggyReauthenticationError(
                                PluggyReauthenticationErrorCode.INTERNAL
                            ) from None

        try:
            return self._store.use_enabled_credentials(
                installation_id=installation_id,
                provider="pluggy",
                operation=verify_and_issue,
            )
        except PluggyReauthenticationError:
            raise
        except ConfigurationNotFoundError:
            raise PluggyReauthenticationError(
                PluggyReauthenticationErrorCode.CONFIGURATION_REQUIRED
            ) from None
        except ProviderNotEnabledError:
            raise PluggyReauthenticationError(
                PluggyReauthenticationErrorCode.PROVIDER_NOT_ENABLED
            ) from None
        except BankingPersistenceError:
            raise PluggyReauthenticationError(
                PluggyReauthenticationErrorCode.INTERNAL
            ) from None
        except Exception:
            raise PluggyReauthenticationError(
                PluggyReauthenticationErrorCode.INTERNAL
            ) from None

    def _load_connection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
    ) -> BankingConnectionRecord:
        try:
            connection = self._store.get_connection(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
            )
        except ConnectionNotFoundError:
            raise PluggyReauthenticationError(
                PluggyReauthenticationErrorCode.CONNECTION_NOT_FOUND
            ) from None
        except BankingPersistenceError:
            raise PluggyReauthenticationError(
                PluggyReauthenticationErrorCode.INTERNAL
            ) from None

        if connection.provider != "pluggy" or (
            connection.status is StoredConnectionStatus.DISCONNECTED
        ):
            raise PluggyReauthenticationError(
                PluggyReauthenticationErrorCode.CONNECTION_NOT_AVAILABLE
            )
        return connection
