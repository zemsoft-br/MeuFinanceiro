from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar
from uuid import UUID

import pytest

from meufinanceiro_banking_pluggy.transport import (
    JsonObject,
    PluggyApplicationCredentials,
    PluggyTransportError,
    PluggyTransportErrorCategory,
)
from meufinanceiro_banking_pluggy_execution import (
    ConnectedItemTransport,
    PluggyConnectionRegistrationError,
    PluggyConnectionRegistrationErrorCode,
    PluggyConnectionRegistrationService,
    RegistrationBankingStore,
)
from meufinanceiro_persistence import (
    BankingConnectionRecord,
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
INSTALLATION_ID = UUID("10000000-0000-4000-8000-000000000001")
RESIDENCE_ID = UUID("20000000-0000-4000-8000-000000000002")
CONNECTION_ID = UUID("30000000-0000-4000-8000-000000000003")
CONFIGURATION_ID = UUID("40000000-0000-4000-8000-000000000004")
ITEM_ID = "synthetic-item-123"
NOW = datetime(2026, 8, 7, tzinfo=UTC)


def _credentials() -> EnabledProviderCredentials:
    return EnabledProviderCredentials(
        configuration_id=CONFIGURATION_ID,
        provider="pluggy",
        configuration_revision=2,
        client_id="synthetic-client-id",
        client_secret="synthetic-client-secret",
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
        "updatedAt": "2026-08-07T00:00:00Z",
        "lastUpdatedAt": "2026-08-07T00:00:00Z",
        "connector": {"products": ["ACCOUNTS", "TRANSACTIONS"]},
    }


def _connection_record(
    *,
    status: StoredConnectionStatus = StoredConnectionStatus.AVAILABLE,
    requires_user_action: bool = False,
) -> BankingConnectionRecord:
    return BankingConnectionRecord(
        id=CONNECTION_ID,
        installation_id=INSTALLATION_ID,
        residence_id=RESIDENCE_ID,
        provider="pluggy",
        external_connection_id=ITEM_ID,
        status=status,
        requires_user_action=requires_user_action,
        last_successful_sync_at=NOW,
        last_attempt_at=NOW,
        next_refresh_allowed_at=None,
        consent_expires_at=None,
        provider_reason_code="SUCCESS",
        disconnected_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


@dataclass
class FakeStore:
    credentials: EnabledProviderCredentials = field(default_factory=_credentials)
    credentials_error: Exception | None = None
    register_error: Exception | None = None
    connection: BankingConnectionRecord = field(default_factory=_connection_record)
    credential_calls: list[tuple[UUID, str]] = field(default_factory=list)
    register_calls: list[dict[str, Any]] = field(default_factory=list)
    capability_calls: list[dict[str, Any]] = field(default_factory=list)

    def use_enabled_credentials(
        self,
        *,
        installation_id: UUID,
        provider: str,
        operation: Callable[[EnabledProviderCredentials], _Result],
    ) -> _Result:
        self.credential_calls.append((installation_id, provider))
        if self.credentials_error is not None:
            raise self.credentials_error
        return operation(self.credentials)

    def register_connection(self, **kwargs: Any) -> BankingConnectionRecord:
        self.register_calls.append(dict(kwargs))
        if self.register_error is not None:
            raise self.register_error
        return self.connection

    def replace_capabilities(self, **kwargs: Any) -> tuple[object, ...]:
        self.capability_calls.append(dict(kwargs))
        return ()


@dataclass
class FakeTransport:
    payload: JsonObject = field(default_factory=_item_payload)
    error: Exception | None = None
    close_error: Exception | None = None
    item_ids: list[str] = field(default_factory=list)
    close_calls: int = 0

    def get_item(self, item_id: str) -> JsonObject:
        self.item_ids.append(item_id)
        if self.error is not None:
            raise self.error
        return self.payload

    def close(self) -> None:
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


def test_protocols_accept_registration_fakes() -> None:
    assert isinstance(FakeStore(), RegistrationBankingStore)
    assert isinstance(FakeTransport(), ConnectedItemTransport)


def test_registration_verifies_ownership_before_persisting_local_connection() -> None:
    store = FakeStore()
    transport = FakeTransport()
    created_credentials: list[PluggyApplicationCredentials] = []

    def factory(credentials: PluggyApplicationCredentials) -> FakeTransport:
        created_credentials.append(credentials)
        return transport

    service = PluggyConnectionRegistrationService(
        store,
        transport_factory=factory,
        clock=lambda: NOW,
    )
    result = service.register(
        installation_id=INSTALLATION_ID,
        residence_id=RESIDENCE_ID,
        item_id=ITEM_ID,
    )

    assert result.connection_id == CONNECTION_ID
    assert result.status is StoredConnectionStatus.AVAILABLE
    assert result.requires_user_action is False
    assert store.credential_calls == [(INSTALLATION_ID, "pluggy")]
    assert transport.item_ids == [ITEM_ID]
    assert transport.close_calls == 1
    assert len(created_credentials) == 1
    assert "synthetic-client-secret" not in repr(created_credentials[0])

    assert len(store.register_calls) == 1
    registered = store.register_calls[0]
    assert registered["installation_id"] == INSTALLATION_ID
    assert registered["residence_id"] == RESIDENCE_ID
    assert registered["provider"] == "pluggy"
    assert registered["external_connection_id"] == ITEM_ID
    assert registered["status"] is StoredConnectionStatus.AVAILABLE
    assert registered["requires_user_action"] is False

    assert len(store.capability_calls) == 1
    snapshots = store.capability_calls[0]["snapshots"]
    assert isinstance(snapshots, tuple)
    capability_map = {snapshot.capability: snapshot for snapshot in snapshots}
    assert capability_map[StoredCapability.TRANSACTIONS].state is (
        StoredCapabilityState.SUPPORTED
    )
    assert capability_map[StoredCapability.TRANSACTIONS].source is (
        StoredCapabilitySource.CONTRACT
    )


def test_registration_is_idempotent_when_store_reuses_same_connection() -> None:
    store = FakeStore()
    service = PluggyConnectionRegistrationService(
        store,
        transport_factory=lambda _: FakeTransport(),
        clock=lambda: NOW,
    )

    first = service.register(
        installation_id=INSTALLATION_ID,
        residence_id=RESIDENCE_ID,
        item_id=ITEM_ID,
    )
    second = service.register(
        installation_id=INSTALLATION_ID,
        residence_id=RESIDENCE_ID,
        item_id=ITEM_ID,
    )

    assert first.connection_id == second.connection_id == CONNECTION_ID
    assert len(store.register_calls) == 2
    assert len(store.capability_calls) == 2


def test_cross_residence_ownership_fails_before_persistence() -> None:
    other_marker = "residence:50000000-0000-4000-8000-000000000005"
    store = FakeStore()
    transport = FakeTransport(payload=_item_payload(client_user_id=other_marker))
    service = PluggyConnectionRegistrationService(
        store,
        transport_factory=lambda _: transport,
        clock=lambda: NOW,
    )

    with pytest.raises(PluggyConnectionRegistrationError) as captured:
        service.register(
            installation_id=INSTALLATION_ID,
            residence_id=RESIDENCE_ID,
            item_id=ITEM_ID,
        )

    assert captured.value.code is PluggyConnectionRegistrationErrorCode.ITEM_NOT_ALLOWED
    assert ITEM_ID not in str(captured.value)
    assert other_marker not in str(captured.value)
    assert store.register_calls == []
    assert store.capability_calls == []
    assert transport.close_calls == 1


@pytest.mark.parametrize(
    ("transport_category", "expected_code"),
    [
        (
            PluggyTransportErrorCategory.NOT_FOUND,
            PluggyConnectionRegistrationErrorCode.ITEM_UNAVAILABLE,
        ),
        (
            PluggyTransportErrorCategory.INVALID_RESPONSE,
            PluggyConnectionRegistrationErrorCode.INVALID_PROVIDER_RESPONSE,
        ),
        (
            PluggyTransportErrorCategory.RATE_LIMITED,
            PluggyConnectionRegistrationErrorCode.TEMPORARILY_UNAVAILABLE,
        ),
        (
            PluggyTransportErrorCategory.AUTHENTICATION,
            PluggyConnectionRegistrationErrorCode.PROVIDER_REJECTED,
        ),
    ],
)
def test_transport_failures_are_stable_and_do_not_persist(
    transport_category: PluggyTransportErrorCategory,
    expected_code: PluggyConnectionRegistrationErrorCode,
) -> None:
    store = FakeStore()
    transport = FakeTransport(
        error=PluggyTransportError(
            transport_category,
            retryable=False,
            provider_reason_code="SENSITIVE_REASON",
        )
    )
    service = PluggyConnectionRegistrationService(
        store,
        transport_factory=lambda _: transport,
        clock=lambda: NOW,
    )

    with pytest.raises(PluggyConnectionRegistrationError) as captured:
        service.register(
            installation_id=INSTALLATION_ID,
            residence_id=RESIDENCE_ID,
            item_id=ITEM_ID,
        )

    assert captured.value.code is expected_code
    assert "SENSITIVE_REASON" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert store.register_calls == []
    assert transport.close_calls == 1


@pytest.mark.parametrize(
    ("store_error", "expected_code"),
    [
        (
            ConfigurationNotFoundError("sensitive-config"),
            PluggyConnectionRegistrationErrorCode.CONFIGURATION_REQUIRED,
        ),
        (
            ProviderNotEnabledError("sensitive-state"),
            PluggyConnectionRegistrationErrorCode.PROVIDER_NOT_ENABLED,
        ),
    ],
)
def test_configuration_failures_are_sanitized(
    store_error: Exception,
    expected_code: PluggyConnectionRegistrationErrorCode,
) -> None:
    store = FakeStore(credentials_error=store_error)
    service = PluggyConnectionRegistrationService(store)

    with pytest.raises(PluggyConnectionRegistrationError) as captured:
        service.register(
            installation_id=INSTALLATION_ID,
            residence_id=RESIDENCE_ID,
            item_id=ITEM_ID,
        )

    assert captured.value.code is expected_code
    assert "sensitive" not in str(captured.value)
    assert store.register_calls == []


def test_cross_residence_persistence_conflict_is_sanitized() -> None:
    store = FakeStore(
        register_error=ConnectionConflictError("sensitive-item-association")
    )
    service = PluggyConnectionRegistrationService(
        store,
        transport_factory=lambda _: FakeTransport(),
        clock=lambda: NOW,
    )

    with pytest.raises(PluggyConnectionRegistrationError) as captured:
        service.register(
            installation_id=INSTALLATION_ID,
            residence_id=RESIDENCE_ID,
            item_id=ITEM_ID,
        )

    assert captured.value.code is PluggyConnectionRegistrationErrorCode.CONNECTION_CONFLICT
    assert "sensitive-item-association" not in str(captured.value)
    assert store.capability_calls == []
