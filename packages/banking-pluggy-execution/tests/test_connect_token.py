from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar
from uuid import UUID

import pytest

from meufinanceiro_banking_pluggy.transport import (
    PluggyApplicationCredentials,
    PluggyTransportError,
    PluggyTransportErrorCategory,
)
from meufinanceiro_banking_pluggy_execution import (
    ConnectTokenBankingStore,
    ConnectTokenTransport,
    IssuedPluggyConnectToken,
    PluggyConnectTokenError,
    PluggyConnectTokenErrorCode,
    PluggyConnectTokenService,
)
from meufinanceiro_persistence import (
    BankingPersistenceError,
    ConfigurationNotFoundError,
    EnabledProviderCredentials,
    ProviderNotEnabledError,
)

_Result = TypeVar("_Result")
INSTALLATION_ID = UUID("10000000-0000-4000-8000-000000000001")
RESIDENCE_ID = UUID("20000000-0000-4000-8000-000000000002")
CONFIGURATION_ID = UUID("30000000-0000-4000-8000-000000000003")


def _credentials() -> EnabledProviderCredentials:
    return EnabledProviderCredentials(
        configuration_id=CONFIGURATION_ID,
        provider="pluggy",
        configuration_revision=2,
        client_id="synthetic-client-id",
        client_secret="synthetic-client-secret",
    )


@dataclass
class FakeStore:
    credentials: EnabledProviderCredentials = field(default_factory=_credentials)
    error: Exception | None = None
    calls: list[tuple[UUID, str]] = field(default_factory=list)

    def use_enabled_credentials(
        self,
        *,
        installation_id: UUID,
        provider: str,
        operation: Callable[[EnabledProviderCredentials], _Result],
    ) -> _Result:
        self.calls.append((installation_id, provider))
        if self.error is not None:
            raise self.error
        return operation(self.credentials)


@dataclass
class FakeTransport:
    token: str = "connect-token-secret"
    error: Exception | None = None
    close_error: Exception | None = None
    client_user_ids: list[str] = field(default_factory=list)
    close_calls: int = 0

    def create_connect_token(self, *, client_user_id: str) -> str:
        self.client_user_ids.append(client_user_id)
        if self.error is not None:
            raise self.error
        return self.token

    def close(self) -> None:
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


def test_protocols_accept_expected_fakes() -> None:
    assert isinstance(FakeStore(), ConnectTokenBankingStore)
    assert isinstance(FakeTransport(), ConnectTokenTransport)


def test_service_derives_residence_scope_and_redacts_token() -> None:
    store = FakeStore()
    transport = FakeTransport()
    created_credentials: list[PluggyApplicationCredentials] = []

    def factory(credentials: PluggyApplicationCredentials) -> FakeTransport:
        created_credentials.append(credentials)
        return transport

    service = PluggyConnectTokenService(store, transport_factory=factory)
    issued = service.issue(
        installation_id=INSTALLATION_ID,
        residence_id=RESIDENCE_ID,
    )

    assert issued.access_token == "connect-token-secret"
    assert repr(issued) == "IssuedPluggyConnectToken(<redacted>)"
    assert "connect-token-secret" not in repr(issued)
    assert store.calls == [(INSTALLATION_ID, "pluggy")]
    assert transport.client_user_ids == [f"residence:{RESIDENCE_ID}"]
    assert transport.close_calls == 1
    assert len(created_credentials) == 1
    assert "synthetic-client-secret" not in repr(created_credentials[0])


def test_issued_token_rejects_invalid_values_without_echoing_them() -> None:
    with pytest.raises(ValueError) as captured:
        IssuedPluggyConnectToken(" invalid-token ")
    assert "invalid-token" not in str(captured.value)


def test_invalid_transport_token_is_invalid_provider_response() -> None:
    transport = FakeTransport(token=" invalid-token ")
    service = PluggyConnectTokenService(
        FakeStore(),
        transport_factory=lambda _: transport,
    )

    with pytest.raises(PluggyConnectTokenError) as captured:
        service.issue(
            installation_id=INSTALLATION_ID,
            residence_id=RESIDENCE_ID,
        )

    assert captured.value.code is PluggyConnectTokenErrorCode.INVALID_PROVIDER_RESPONSE
    assert "invalid-token" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert transport.close_calls == 1


@pytest.mark.parametrize(
    ("store_error", "expected_code"),
    [
        (
            ConfigurationNotFoundError("synthetic-sensitive-config"),
            PluggyConnectTokenErrorCode.CONFIGURATION_REQUIRED,
        ),
        (
            ProviderNotEnabledError("synthetic-sensitive-state"),
            PluggyConnectTokenErrorCode.PROVIDER_NOT_ENABLED,
        ),
        (
            BankingPersistenceError("synthetic-sensitive-database"),
            PluggyConnectTokenErrorCode.INTERNAL,
        ),
    ],
)
def test_store_failures_are_stable_and_sanitized(
    store_error: Exception,
    expected_code: PluggyConnectTokenErrorCode,
) -> None:
    service = PluggyConnectTokenService(FakeStore(error=store_error))

    with pytest.raises(PluggyConnectTokenError) as captured:
        service.issue(
            installation_id=INSTALLATION_ID,
            residence_id=RESIDENCE_ID,
        )

    assert captured.value.code is expected_code
    assert "synthetic-sensitive" not in str(captured.value)
    assert captured.value.__cause__ is None


@pytest.mark.parametrize(
    ("category", "expected_code"),
    [
        (
            PluggyTransportErrorCategory.RATE_LIMITED,
            PluggyConnectTokenErrorCode.TEMPORARILY_UNAVAILABLE,
        ),
        (
            PluggyTransportErrorCategory.TEMPORARILY_UNAVAILABLE,
            PluggyConnectTokenErrorCode.TEMPORARILY_UNAVAILABLE,
        ),
        (
            PluggyTransportErrorCategory.INVALID_RESPONSE,
            PluggyConnectTokenErrorCode.INVALID_PROVIDER_RESPONSE,
        ),
        (
            PluggyTransportErrorCategory.AUTHENTICATION,
            PluggyConnectTokenErrorCode.PROVIDER_REJECTED,
        ),
        (
            PluggyTransportErrorCategory.INVALID_REQUEST,
            PluggyConnectTokenErrorCode.PROVIDER_REJECTED,
        ),
        (
            PluggyTransportErrorCategory.INTERNAL,
            PluggyConnectTokenErrorCode.INTERNAL,
        ),
    ],
)
def test_transport_failures_are_sanitized_and_transport_is_closed(
    category: PluggyTransportErrorCategory,
    expected_code: PluggyConnectTokenErrorCode,
) -> None:
    transport = FakeTransport(
        error=PluggyTransportError(
            category,
            retryable=False,
            provider_reason_code="SYNTHETIC_REASON",
        )
    )
    service = PluggyConnectTokenService(
        FakeStore(),
        transport_factory=lambda _: transport,
    )

    with pytest.raises(PluggyConnectTokenError) as captured:
        service.issue(
            installation_id=INSTALLATION_ID,
            residence_id=RESIDENCE_ID,
        )

    assert captured.value.code is expected_code
    assert captured.value.__cause__ is None
    assert "SYNTHETIC_REASON" not in str(captured.value)
    assert transport.close_calls == 1


def test_close_failure_is_sanitized() -> None:
    transport = FakeTransport(close_error=RuntimeError("connect-token-secret"))
    service = PluggyConnectTokenService(
        FakeStore(),
        transport_factory=lambda _: transport,
    )

    with pytest.raises(PluggyConnectTokenError) as captured:
        service.issue(
            installation_id=INSTALLATION_ID,
            residence_id=RESIDENCE_ID,
        )

    assert captured.value.code is PluggyConnectTokenErrorCode.INTERNAL
    assert "connect-token-secret" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert transport.close_calls == 1
