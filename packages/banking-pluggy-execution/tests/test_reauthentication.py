from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID

import pytest

from meufinanceiro_banking_pluggy.transport import (
    JsonObject,
    PluggyApplicationCredentials,
    PluggyTransportError,
    PluggyTransportErrorCategory,
)
from meufinanceiro_banking_pluggy_execution import (
    PluggyReauthenticationError,
    PluggyReauthenticationErrorCode,
    PluggyReauthenticationTokenService,
    ReauthenticationBankingStore,
    ReauthenticationTransport,
)
from meufinanceiro_persistence import (
    BankingConnectionRecord,
    ConnectionNotFoundError,
    EnabledProviderCredentials,
    StoredConnectionStatus,
)

_Result = TypeVar("_Result")
INSTALLATION_ID = UUID("10000000-0000-4000-8000-000000000001")
RESIDENCE_ID = UUID("20000000-0000-4000-8000-000000000002")
CONNECTION_ID = UUID("30000000-0000-4000-8000-000000000003")
CONFIGURATION_ID = UUID("40000000-0000-4000-8000-000000000004")
ITEM_ID = "synthetic-existing-item"
CONNECT_TOKEN = "synthetic-update-connect-token"
NOW = datetime(2026, 8, 8, tzinfo=UTC)


def _credentials() -> EnabledProviderCredentials:
    return EnabledProviderCredentials(
        configuration_id=CONFIGURATION_ID,
        provider="pluggy",
        configuration_revision=2,
        client_id="synthetic-client-id",
        client_secret="synthetic-client-secret",
    )


def _connection(
    *,
    provider: str = "pluggy",
    status: StoredConnectionStatus = StoredConnectionStatus.AVAILABLE,
) -> BankingConnectionRecord:
    return BankingConnectionRecord(
        id=CONNECTION_ID,
        installation_id=INSTALLATION_ID,
        residence_id=RESIDENCE_ID,
        provider=provider,
        external_connection_id=ITEM_ID,
        status=status,
        requires_user_action=(
            status is StoredConnectionStatus.REAUTHENTICATION_REQUIRED
        ),
        last_successful_sync_at=NOW,
        last_attempt_at=NOW,
        next_refresh_allowed_at=None,
        consent_expires_at=None,
        provider_reason_code=None,
        disconnected_at=(NOW if status is StoredConnectionStatus.DISCONNECTED else None),
        created_at=NOW,
        updated_at=NOW,
    )


def _item_payload(
    *,
    client_user_id: str = f"residence:{RESIDENCE_ID}",
) -> JsonObject:
    return {
        "id": ITEM_ID,
        "clientUserId": client_user_id,
        "status": "UPDATED",
        "executionStatus": "SUCCESS",
        "updatedAt": "2026-08-08T00:00:00Z",
        "lastUpdatedAt": "2026-08-08T00:00:00Z",
        "connector": {"products": ["ACCOUNTS", "TRANSACTIONS"]},
    }


@dataclass
class FakeStore:
    connection: BankingConnectionRecord = field(default_factory=_connection)
    connection_error: Exception | None = None
    credentials: EnabledProviderCredentials = field(default_factory=_credentials)
    connection_calls: list[tuple[UUID, UUID, UUID]] = field(default_factory=list)
    credential_calls: list[tuple[UUID, str]] = field(default_factory=list)

    def get_connection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
    ) -> BankingConnectionRecord:
        self.connection_calls.append((installation_id, residence_id, connection_id))
        if self.connection_error is not None:
            raise self.connection_error
        return self.connection

    def use_enabled_credentials(
        self,
        *,
        installation_id: UUID,
        provider: str,
        operation: Callable[[EnabledProviderCredentials], _Result],
    ) -> _Result:
        self.credential_calls.append((installation_id, provider))
        return operation(self.credentials)


@dataclass
class FakeTransport:
    payload: JsonObject = field(default_factory=_item_payload)
    token: str = CONNECT_TOKEN
    item_error: Exception | None = None
    token_error: Exception | None = None
    item_calls: list[str] = field(default_factory=list)
    token_calls: list[str] = field(default_factory=list)
    close_calls: int = 0

    def get_item(self, item_id: str) -> JsonObject:
        self.item_calls.append(item_id)
        if self.item_error is not None:
            raise self.item_error
        return self.payload

    def create_update_connect_token(self, *, item_id: str) -> str:
        self.token_calls.append(item_id)
        if self.token_error is not None:
            raise self.token_error
        return self.token

    def close(self) -> None:
        self.close_calls += 1


def test_protocols_accept_reauthentication_fakes() -> None:
    assert isinstance(FakeStore(), ReauthenticationBankingStore)
    assert isinstance(FakeTransport(), ReauthenticationTransport)


def test_reauthentication_verifies_ownership_before_issuing_update_token() -> None:
    store = FakeStore(
        connection=_connection(
            status=StoredConnectionStatus.REAUTHENTICATION_REQUIRED,
        )
    )
    transport = FakeTransport()
    created_credentials: list[PluggyApplicationCredentials] = []

    def factory(credentials: PluggyApplicationCredentials) -> FakeTransport:
        created_credentials.append(credentials)
        return transport

    service = PluggyReauthenticationTokenService(store, transport_factory=factory)
    issued = service.issue(
        installation_id=INSTALLATION_ID,
        residence_id=RESIDENCE_ID,
        connection_id=CONNECTION_ID,
    )

    assert issued.access_token == CONNECT_TOKEN
    assert issued.item_id == ITEM_ID
    assert CONNECT_TOKEN not in repr(issued)
    assert ITEM_ID not in repr(issued)
    assert store.connection_calls == [(INSTALLATION_ID, RESIDENCE_ID, CONNECTION_ID)]
    assert store.credential_calls == [(INSTALLATION_ID, "pluggy")]
    assert transport.item_calls == [ITEM_ID]
    assert transport.token_calls == [ITEM_ID]
    assert transport.close_calls == 1
    assert len(created_credentials) == 1
    assert "synthetic-client-secret" not in repr(created_credentials[0])


def test_ownership_mismatch_does_not_issue_connect_token() -> None:
    marker = "residence:50000000-0000-4000-8000-000000000005"
    store = FakeStore()
    transport = FakeTransport(payload=_item_payload(client_user_id=marker))
    service = PluggyReauthenticationTokenService(
        store,
        transport_factory=lambda _: transport,
    )

    with pytest.raises(PluggyReauthenticationError) as captured:
        service.issue(
            installation_id=INSTALLATION_ID,
            residence_id=RESIDENCE_ID,
            connection_id=CONNECTION_ID,
        )

    assert (
        captured.value.code
        is PluggyReauthenticationErrorCode.CONNECTION_NOT_ALLOWED
    )
    assert ITEM_ID not in str(captured.value)
    assert marker not in str(captured.value)
    assert transport.token_calls == []
    assert transport.close_calls == 1


def test_cross_residence_not_found_stops_before_credentials() -> None:
    store = FakeStore(connection_error=ConnectionNotFoundError("sensitive-local-id"))
    service = PluggyReauthenticationTokenService(store)

    with pytest.raises(PluggyReauthenticationError) as captured:
        service.issue(
            installation_id=INSTALLATION_ID,
            residence_id=RESIDENCE_ID,
            connection_id=CONNECTION_ID,
        )

    assert captured.value.code is PluggyReauthenticationErrorCode.CONNECTION_NOT_FOUND
    assert store.credential_calls == []
    assert "sensitive-local-id" not in str(captured.value)


@pytest.mark.parametrize(
    "connection",
    [
        _connection(provider="other_provider"),
        _connection(status=StoredConnectionStatus.DISCONNECTED),
    ],
)
def test_incompatible_or_disconnected_connection_stops_before_credentials(
    connection: BankingConnectionRecord,
) -> None:
    store = FakeStore(connection=connection)
    service = PluggyReauthenticationTokenService(store)

    with pytest.raises(PluggyReauthenticationError) as captured:
        service.issue(
            installation_id=INSTALLATION_ID,
            residence_id=RESIDENCE_ID,
            connection_id=CONNECTION_ID,
        )

    assert (
        captured.value.code
        is PluggyReauthenticationErrorCode.CONNECTION_NOT_AVAILABLE
    )
    assert store.credential_calls == []


def test_ambiguous_connect_token_failure_is_sanitized_and_transport_closes() -> None:
    store = FakeStore()
    transport = FakeTransport(
        token_error=PluggyTransportError(
            PluggyTransportErrorCategory.TEMPORARILY_UNAVAILABLE,
            retryable=True,
            provider_reason_code="SENSITIVE_PROVIDER_REASON",
        )
    )
    service = PluggyReauthenticationTokenService(
        store,
        transport_factory=lambda _: transport,
    )

    with pytest.raises(PluggyReauthenticationError) as captured:
        service.issue(
            installation_id=INSTALLATION_ID,
            residence_id=RESIDENCE_ID,
            connection_id=CONNECTION_ID,
        )

    assert (
        captured.value.code
        is PluggyReauthenticationErrorCode.TEMPORARILY_UNAVAILABLE
    )
    assert "SENSITIVE_PROVIDER_REASON" not in str(captured.value)
    assert ITEM_ID not in str(captured.value)
    assert captured.value.__cause__ is None
    assert transport.close_calls == 1
