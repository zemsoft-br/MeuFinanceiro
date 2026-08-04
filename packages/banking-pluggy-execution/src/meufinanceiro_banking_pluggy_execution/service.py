"""Residence-scoped one-shot Pluggy read-only execution."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol, TypeAlias, TypeVar, cast, runtime_checkable
from uuid import UUID

from meufinanceiro_banking import (
    BankingProvider,
    BankingProviderError,
    ConnectionCapability,
    ConnectionState,
    ExternalAccount,
    ExternalPage,
    ExternalTransaction,
    ProviderErrorCategory,
)
from meufinanceiro_banking_pluggy import (
    PluggyBankingProvider,
    PluggyGatewayHttpTransport,
    PluggyHttpReadOnlyGateway,
)
from meufinanceiro_banking_pluggy.http_gateway import PluggyPayloadTransport
from meufinanceiro_banking_pluggy.transport import (
    JsonObject,
    PluggyApplicationCredentials,
)
from meufinanceiro_persistence import (
    BankingConnectionRecord,
    EnabledProviderCredentials,
    StoredConnectionStatus,
)

_Result = TypeVar("_Result")
ProviderOperation: TypeAlias = Callable[[BankingProvider], _Result]

_MAX_IDENTIFIER_LENGTH = 512


@runtime_checkable
class ContextualBankingStore(Protocol):
    """Persistence operations required by the read-only executor."""

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
class PluggyExecutionTransport(Protocol):
    """Closable payload transport created only for one executor operation."""

    def get_item(self, item_id: str) -> JsonObject: ...

    def get_accounts(self, item_id: str) -> JsonObject: ...

    def get_transactions_page(
        self,
        account_id: str,
        *,
        after: str | None,
        created_at_from: datetime | None,
    ) -> JsonObject: ...

    def close(self) -> None: ...


TransportFactory: TypeAlias = Callable[
    [PluggyApplicationCredentials],
    PluggyExecutionTransport,
]


def _default_transport_factory(
    credentials: PluggyApplicationCredentials,
) -> PluggyExecutionTransport:
    return PluggyGatewayHttpTransport(credentials)


def _clean_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_IDENTIFIER_LENGTH:
        raise ValueError(f"{field_name} is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ValueError(f"{field_name} contains control characters")
    return normalized


def _clean_optional_identifier(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _clean_identifier(value, field_name)


def _require_aware(value: datetime | None, field_name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{field_name} must be timezone-aware")


class PluggyReadOnlyExecutionService:
    """Execute fixed Pluggy reads from a residence-scoped persisted connection."""

    def __init__(
        self,
        store: ContextualBankingStore,
        *,
        transport_factory: TransportFactory = _default_transport_factory,
    ) -> None:
        if not isinstance(store, ContextualBankingStore):
            raise TypeError("store must satisfy ContextualBankingStore")
        if not callable(transport_factory):
            raise TypeError("transport_factory must be callable")
        self._store = store
        self._transport_factory = transport_factory

    def get_connection_state(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
    ) -> ConnectionState:
        connection = self._load_connection(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
        )
        return self._execute(
            installation_id=installation_id,
            connection=connection,
            operation=lambda provider: provider.get_connection(
                connection.external_connection_id
            ),
        )

    def get_capabilities(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
    ) -> tuple[ConnectionCapability, ...]:
        connection = self._load_connection(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
        )
        return self._execute(
            installation_id=installation_id,
            connection=connection,
            operation=lambda provider: provider.get_capabilities(
                connection.external_connection_id
            ),
        )

    def list_accounts(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
    ) -> tuple[ExternalAccount, ...]:
        connection = self._load_connection(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
        )
        return self._execute(
            installation_id=installation_id,
            connection=connection,
            operation=lambda provider: provider.list_accounts(
                connection.external_connection_id
            ),
        )

    def list_transactions(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        external_account_id: str,
        cursor: str | None = None,
        changed_since: datetime | None = None,
    ) -> ExternalPage[ExternalTransaction]:
        account_id = _clean_identifier(external_account_id, "external_account_id")
        normalized_cursor = _clean_optional_identifier(cursor, "cursor")
        _require_aware(changed_since, "changed_since")
        connection = self._load_connection(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
        )

        def read_transactions(
            provider: BankingProvider,
        ) -> ExternalPage[ExternalTransaction]:
            accounts = provider.list_accounts(connection.external_connection_id)
            if not any(
                account.external_account_id == account_id
                and account.external_connection_id == connection.external_connection_id
                for account in accounts
            ):
                raise BankingProviderError(
                    ProviderErrorCategory.NOT_FOUND,
                    retryable=False,
                    provider_reason_code="ACCOUNT_NOT_IN_CONNECTION",
                )
            return provider.list_transactions(
                account_id,
                normalized_cursor,
                changed_since,
            )

        return self._execute(
            installation_id=installation_id,
            connection=connection,
            operation=read_transactions,
        )

    def _load_connection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
    ) -> BankingConnectionRecord:
        connection = self._store.get_connection(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
        )
        if connection.provider != "pluggy":
            raise BankingProviderError(
                ProviderErrorCategory.UNSUPPORTED,
                retryable=False,
                provider_reason_code="PROVIDER_NOT_SUPPORTED",
            )
        if connection.status is StoredConnectionStatus.DISCONNECTED:
            raise BankingProviderError(
                ProviderErrorCategory.INVALID_REQUEST,
                retryable=False,
                provider_reason_code="CONNECTION_DISCONNECTED",
            )
        return connection

    def _execute(
        self,
        *,
        installation_id: UUID,
        connection: BankingConnectionRecord,
        operation: ProviderOperation[_Result],
    ) -> _Result:
        def with_credentials(credentials: EnabledProviderCredentials) -> _Result:
            if credentials.provider != connection.provider:
                raise BankingProviderError(
                    ProviderErrorCategory.INTERNAL,
                    retryable=False,
                    provider_reason_code="CREDENTIAL_PROVIDER_MISMATCH",
                )
            transport: PluggyExecutionTransport | None = None
            active_error: BaseException | None = None
            try:
                application_credentials = PluggyApplicationCredentials(
                    credentials.client_id,
                    credentials.client_secret,
                )
                transport = self._transport_factory(application_credentials)
                if not isinstance(transport, PluggyExecutionTransport):
                    raise TypeError("transport factory returned an invalid object")
                gateway = PluggyHttpReadOnlyGateway(
                    cast(PluggyPayloadTransport, transport)
                )
                provider: BankingProvider = PluggyBankingProvider(gateway)
                return operation(provider)
            except BankingProviderError as error:
                active_error = error
                raise
            except Exception as error:
                active_error = error
                raise BankingProviderError(
                    ProviderErrorCategory.INTERNAL,
                    retryable=False,
                    provider_reason_code="PROVIDER_EXECUTION_FAILED",
                ) from None
            finally:
                if transport is not None:
                    try:
                        transport.close()
                    except Exception:
                        if active_error is None:
                            raise BankingProviderError(
                                ProviderErrorCategory.INTERNAL,
                                retryable=False,
                                provider_reason_code="TRANSPORT_CLOSE_FAILED",
                            ) from None

        return self._store.use_enabled_credentials(
            installation_id=installation_id,
            provider=connection.provider,
            operation=with_credentials,
        )
