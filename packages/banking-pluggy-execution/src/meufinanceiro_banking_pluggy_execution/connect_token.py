"""Residence-scoped Pluggy Connect Token issuance with ephemeral credentials."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypeAlias, TypeVar, runtime_checkable
from uuid import UUID

from meufinanceiro_banking_pluggy import PluggyConnectTokenHttpTransport
from meufinanceiro_banking_pluggy.transport import (
    PluggyApplicationCredentials,
    PluggyTransportError,
    PluggyTransportErrorCategory,
)
from meufinanceiro_persistence import (
    BankingPersistenceError,
    ConfigurationNotFoundError,
    EnabledProviderCredentials,
    ProviderNotEnabledError,
)

_Result = TypeVar("_Result")
_MAX_TOKEN_LENGTH = 4096


class PluggyConnectTokenErrorCode(StrEnum):
    CONFIGURATION_REQUIRED = "CONFIGURATION_REQUIRED"
    PROVIDER_NOT_ENABLED = "PROVIDER_NOT_ENABLED"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    INVALID_PROVIDER_RESPONSE = "INVALID_PROVIDER_RESPONSE"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    INTERNAL = "INTERNAL"


_ERROR_MESSAGES = {
    PluggyConnectTokenErrorCode.CONFIGURATION_REQUIRED: (
        "banking provider configuration is required"
    ),
    PluggyConnectTokenErrorCode.PROVIDER_NOT_ENABLED: (
        "banking provider must be enabled"
    ),
    PluggyConnectTokenErrorCode.TEMPORARILY_UNAVAILABLE: (
        "banking provider is temporarily unavailable"
    ),
    PluggyConnectTokenErrorCode.INVALID_PROVIDER_RESPONSE: (
        "banking provider returned an invalid response"
    ),
    PluggyConnectTokenErrorCode.PROVIDER_REJECTED: (
        "banking provider rejected the operation"
    ),
    PluggyConnectTokenErrorCode.INTERNAL: "banking connection token is unavailable",
}


class PluggyConnectTokenError(RuntimeError):
    """Stable error boundary that never carries provider payloads or tokens."""

    __slots__ = ("code",)

    def __init__(self, code: PluggyConnectTokenErrorCode) -> None:
        if not isinstance(code, PluggyConnectTokenErrorCode):
            raise TypeError("code must be PluggyConnectTokenErrorCode")
        super().__init__(_ERROR_MESSAGES[code])
        self.code = code


@dataclass(frozen=True, slots=True, repr=False)
class IssuedPluggyConnectToken:
    access_token: str

    def __post_init__(self) -> None:
        value = self.access_token
        if not isinstance(value, str):
            raise TypeError("access_token must be a string")
        if value != value.strip() or not value:
            raise ValueError("access_token is invalid")
        if len(value) > _MAX_TOKEN_LENGTH:
            raise ValueError("access_token exceeds the maximum length")
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("access_token contains control characters")

    def __repr__(self) -> str:
        return "IssuedPluggyConnectToken(<redacted>)"


@runtime_checkable
class ConnectTokenBankingStore(Protocol):
    def use_enabled_credentials(
        self,
        *,
        installation_id: UUID,
        provider: str,
        operation: Callable[[EnabledProviderCredentials], _Result],
    ) -> _Result: ...


@runtime_checkable
class ConnectTokenTransport(Protocol):
    def create_connect_token(self, *, client_user_id: str) -> str: ...

    def close(self) -> None: ...


ConnectTokenTransportFactory: TypeAlias = Callable[
    [PluggyApplicationCredentials],
    ConnectTokenTransport,
]


def _default_transport_factory(
    credentials: PluggyApplicationCredentials,
) -> ConnectTokenTransport:
    return PluggyConnectTokenHttpTransport(credentials)


def _map_transport_error(error: PluggyTransportError) -> PluggyConnectTokenError:
    if error.category in {
        PluggyTransportErrorCategory.RATE_LIMITED,
        PluggyTransportErrorCategory.TEMPORARILY_UNAVAILABLE,
    }:
        code = PluggyConnectTokenErrorCode.TEMPORARILY_UNAVAILABLE
    elif error.category is PluggyTransportErrorCategory.INVALID_RESPONSE:
        code = PluggyConnectTokenErrorCode.INVALID_PROVIDER_RESPONSE
    elif error.category in {
        PluggyTransportErrorCategory.AUTHENTICATION,
        PluggyTransportErrorCategory.AUTHORIZATION,
        PluggyTransportErrorCategory.INVALID_REQUEST,
        PluggyTransportErrorCategory.NOT_FOUND,
    }:
        code = PluggyConnectTokenErrorCode.PROVIDER_REJECTED
    else:
        code = PluggyConnectTokenErrorCode.INTERNAL
    return PluggyConnectTokenError(code)


class PluggyConnectTokenService:
    """Issue a token for one authenticated canonical residence."""

    def __init__(
        self,
        store: ConnectTokenBankingStore,
        *,
        transport_factory: ConnectTokenTransportFactory = _default_transport_factory,
    ) -> None:
        if not isinstance(store, ConnectTokenBankingStore):
            raise TypeError("store must satisfy ConnectTokenBankingStore")
        if not callable(transport_factory):
            raise TypeError("transport_factory must be callable")
        self._store = store
        self._transport_factory = transport_factory

    def issue(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
    ) -> IssuedPluggyConnectToken:
        if not isinstance(installation_id, UUID):
            raise TypeError("installation_id must be UUID")
        if not isinstance(residence_id, UUID):
            raise TypeError("residence_id must be UUID")
        client_user_id = f"residence:{residence_id}"

        def with_credentials(
            credentials: EnabledProviderCredentials,
        ) -> IssuedPluggyConnectToken:
            if credentials.provider != "pluggy":
                raise PluggyConnectTokenError(
                    PluggyConnectTokenErrorCode.INTERNAL
                )
            transport: ConnectTokenTransport | None = None
            active_error: BaseException | None = None
            try:
                application_credentials = PluggyApplicationCredentials(
                    credentials.client_id,
                    credentials.client_secret,
                )
                transport = self._transport_factory(application_credentials)
                if not isinstance(transport, ConnectTokenTransport):
                    raise TypeError("transport factory returned an invalid object")
                token = transport.create_connect_token(
                    client_user_id=client_user_id,
                )
                return IssuedPluggyConnectToken(token)
            except PluggyConnectTokenError as error:
                active_error = error
                raise
            except PluggyTransportError as error:
                active_error = error
                raise _map_transport_error(error) from None
            except Exception as error:
                active_error = error
                raise PluggyConnectTokenError(
                    PluggyConnectTokenErrorCode.INTERNAL
                ) from None
            finally:
                if transport is not None:
                    try:
                        transport.close()
                    except Exception:
                        if active_error is None:
                            raise PluggyConnectTokenError(
                                PluggyConnectTokenErrorCode.INTERNAL
                            ) from None

        try:
            return self._store.use_enabled_credentials(
                installation_id=installation_id,
                provider="pluggy",
                operation=with_credentials,
            )
        except PluggyConnectTokenError:
            raise
        except ConfigurationNotFoundError:
            raise PluggyConnectTokenError(
                PluggyConnectTokenErrorCode.CONFIGURATION_REQUIRED
            ) from None
        except ProviderNotEnabledError:
            raise PluggyConnectTokenError(
                PluggyConnectTokenErrorCode.PROVIDER_NOT_ENABLED
            ) from None
        except BankingPersistenceError:
            raise PluggyConnectTokenError(
                PluggyConnectTokenErrorCode.INTERNAL
            ) from None
        except Exception:
            raise PluggyConnectTokenError(
                PluggyConnectTokenErrorCode.INTERNAL
            ) from None
