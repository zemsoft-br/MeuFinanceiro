from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from meufinanceiro_banking import (
    BankingProviderError,
    ConnectionState,
    ConnectionStatus,
    FakeBankingProvider,
    ProviderErrorCategory,
)
from meufinanceiro_banking_sync import (
    BankingConnectionDisconnectionService,
    ConnectionDisconnectionError,
    ConnectionDisconnectionErrorCode,
    ConnectionDisconnectionOutcome,
)
from meufinanceiro_persistence import (
    BankingConnectionRecord,
    BankingPersistenceError,
    ConnectionNotFoundError,
    StoredConnectionStatus,
    SyncConflictError,
)

NOW = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
INSTALLATION_ID = UUID("00000000-0000-4000-8000-000000000201")
RESIDENCE_ID = UUID("00000000-0000-4000-8000-000000000202")
OPERATOR_ID = UUID("00000000-0000-4000-8000-000000000203")
CONNECTION_ID = UUID("00000000-0000-4000-8000-000000000204")
OTHER_RESIDENCE_ID = UUID("00000000-0000-4000-8000-000000000205")
EXTERNAL_CONNECTION_ID = "provider-private-connection-id"


def _local_connection(
    *,
    status: StoredConnectionStatus = StoredConnectionStatus.AVAILABLE,
) -> BankingConnectionRecord:
    disconnected_at = NOW if status is StoredConnectionStatus.DISCONNECTED else None
    return BankingConnectionRecord(
        id=CONNECTION_ID,
        installation_id=INSTALLATION_ID,
        residence_id=RESIDENCE_ID,
        provider="fake",
        external_connection_id=EXTERNAL_CONNECTION_ID,
        status=status,
        requires_user_action=False,
        last_successful_sync_at=None,
        last_attempt_at=None,
        next_refresh_allowed_at=None,
        consent_expires_at=None,
        provider_reason_code=None,
        disconnected_at=disconnected_at,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeDisconnectionStore:
    def __init__(
        self,
        record: BankingConnectionRecord,
        *,
        busy: bool = False,
    ) -> None:
        self.record = record
        self.busy = busy
        self.fail_after_operation = False
        self.operation_calls = 0

    def get_connection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
    ) -> BankingConnectionRecord:
        if (
            installation_id != self.record.installation_id
            or residence_id != self.record.residence_id
            or connection_id != self.record.id
        ):
            raise ConnectionNotFoundError("banking connection was not found")
        return self.record

    def execute_connection_disconnection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        operation,
    ) -> bool:
        current = self.get_connection(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
        )

        if current.status is StoredConnectionStatus.DISCONNECTED:
            return False

        if self.busy:
            raise SyncConflictError(
                "active banking synchronization prevents disconnection"
            )

        self.operation_calls += 1
        operation()

        if self.fail_after_operation:
            self.fail_after_operation = False
            raise BankingPersistenceError("synthetic local finalization failure")

        self.record = replace(
            current,
            status=StoredConnectionStatus.DISCONNECTED,
            requires_user_action=False,
            next_refresh_allowed_at=None,
            provider_reason_code=None,
            disconnected_at=NOW,
            updated_at=NOW,
        )
        return True


class CountingProvider(FakeBankingProvider):
    def __init__(self) -> None:
        super().__init__(clock=lambda: NOW)
        self.get_connection_calls = 0
        self.disconnect_calls = 0

    def get_connection(self, external_connection_id: str) -> ConnectionState:
        self.get_connection_calls += 1
        return super().get_connection(external_connection_id)

    def disconnect(self, external_connection_id: str, actor_id: str) -> None:
        self.disconnect_calls += 1
        super().disconnect(external_connection_id, actor_id)


class UnsupportedDisconnectProvider(CountingProvider):
    def disconnect(self, external_connection_id: str, actor_id: str) -> None:
        del external_connection_id, actor_id
        self.disconnect_calls += 1
        raise BankingProviderError(
            ProviderErrorCategory.UNSUPPORTED,
            retryable=False,
            provider_reason_code="UNSUPPORTED_OPERATION",
            safe_message="synthetic unsupported operation",
        )


def _provider(
    *,
    status: ConnectionStatus = ConnectionStatus.AVAILABLE,
    provider_type=CountingProvider,
):
    provider = provider_type()
    provider.seed_connection(
        ConnectionState(
            external_connection_id=EXTERNAL_CONNECTION_ID,
            status=status,
            capabilities=(),
        ),
        residence_id=str(RESIDENCE_ID),
    )
    return provider


def _disconnect(service: BankingConnectionDisconnectionService):
    return service.disconnect(
        installation_id=INSTALLATION_ID,
        residence_id=RESIDENCE_ID,
        operator_id=OPERATOR_ID,
        connection_id=CONNECTION_ID,
    )


def test_disconnect_then_local_replay_never_repeats_provider_mutation() -> None:
    provider = _provider()
    store = FakeDisconnectionStore(_local_connection())
    service = BankingConnectionDisconnectionService(provider, store)

    first = _disconnect(service)

    provider_reads_after_first = provider.get_connection_calls
    disconnect_calls_after_first = provider.disconnect_calls
    store_calls_after_first = store.operation_calls

    second = _disconnect(service)

    assert first.outcome is ConnectionDisconnectionOutcome.DISCONNECTED
    assert second.outcome is ConnectionDisconnectionOutcome.ALREADY_DISCONNECTED
    assert disconnect_calls_after_first == 1
    assert provider.disconnect_calls == disconnect_calls_after_first
    assert provider.get_connection_calls == provider_reads_after_first
    assert store.operation_calls == store_calls_after_first
    assert store.record.status is StoredConnectionStatus.DISCONNECTED

    representation = repr(first)
    assert EXTERNAL_CONNECTION_ID not in representation
    assert str(CONNECTION_ID) not in representation
    assert "fake" not in representation


def test_provider_already_disconnected_recovers_local_state_without_disconnect() -> (
    None
):
    provider = _provider(status=ConnectionStatus.DISCONNECTED)
    store = FakeDisconnectionStore(_local_connection())
    service = BankingConnectionDisconnectionService(provider, store)

    result = _disconnect(service)

    assert result.outcome is ConnectionDisconnectionOutcome.RECOVERED
    assert provider.get_connection_calls == 1
    assert provider.disconnect_calls == 0
    assert store.record.status is StoredConnectionStatus.DISCONNECTED


def test_provider_unsupported_leaves_local_state_unchanged_and_sanitized() -> None:
    provider = _provider(provider_type=UnsupportedDisconnectProvider)
    store = FakeDisconnectionStore(_local_connection())
    service = BankingConnectionDisconnectionService(provider, store)

    with pytest.raises(ConnectionDisconnectionError) as captured:
        _disconnect(service)

    error = captured.value
    assert error.code is ConnectionDisconnectionErrorCode.PROVIDER_UNSUPPORTED
    assert str(error) == "banking provider does not support disconnection"
    assert EXTERNAL_CONNECTION_ID not in str(error)
    assert "UNSUPPORTED_OPERATION" not in str(error)
    assert provider.disconnect_calls == 1
    assert store.record.status is StoredConnectionStatus.AVAILABLE
    assert store.record.disconnected_at is None


def test_active_sync_fails_before_any_provider_io() -> None:
    provider = _provider()
    store = FakeDisconnectionStore(_local_connection(), busy=True)
    service = BankingConnectionDisconnectionService(provider, store)

    with pytest.raises(ConnectionDisconnectionError) as captured:
        _disconnect(service)

    assert captured.value.code is ConnectionDisconnectionErrorCode.CONNECTION_BUSY
    assert provider.get_connection_calls == 0
    assert provider.disconnect_calls == 0
    assert store.record.status is StoredConnectionStatus.AVAILABLE


def test_external_success_then_local_failure_recovers_without_second_disconnect() -> (
    None
):
    provider = _provider()
    store = FakeDisconnectionStore(_local_connection())
    store.fail_after_operation = True
    service = BankingConnectionDisconnectionService(provider, store)

    with pytest.raises(ConnectionDisconnectionError) as captured:
        _disconnect(service)

    assert captured.value.code is ConnectionDisconnectionErrorCode.INTERNAL
    assert provider.disconnect_calls == 1
    assert (
        provider.get_connection(EXTERNAL_CONNECTION_ID).status
        is ConnectionStatus.DISCONNECTED
    )
    assert store.record.status is StoredConnectionStatus.AVAILABLE
    assert store.record.disconnected_at is None

    get_calls_before_recovery = provider.get_connection_calls

    recovered = _disconnect(service)

    assert recovered.outcome is ConnectionDisconnectionOutcome.RECOVERED
    assert provider.disconnect_calls == 1
    assert provider.get_connection_calls == get_calls_before_recovery + 1
    assert store.record.status is StoredConnectionStatus.DISCONNECTED


def test_cross_residence_is_fail_closed_without_provider_io() -> None:
    provider = _provider()
    store = FakeDisconnectionStore(_local_connection())
    service = BankingConnectionDisconnectionService(provider, store)

    with pytest.raises(ConnectionDisconnectionError) as captured:
        service.disconnect(
            installation_id=INSTALLATION_ID,
            residence_id=OTHER_RESIDENCE_ID,
            operator_id=OPERATOR_ID,
            connection_id=CONNECTION_ID,
        )

    assert captured.value.code is ConnectionDisconnectionErrorCode.CONNECTION_NOT_FOUND
    assert provider.get_connection_calls == 0
    assert provider.disconnect_calls == 0
    assert EXTERNAL_CONNECTION_ID not in str(captured.value)


def test_provider_mismatch_fails_closed_without_external_io() -> None:
    provider = _provider()
    store = FakeDisconnectionStore(
        replace(_local_connection(), provider="another_provider")
    )
    service = BankingConnectionDisconnectionService(provider, store)

    with pytest.raises(ConnectionDisconnectionError) as captured:
        _disconnect(service)

    assert (
        captured.value.code is ConnectionDisconnectionErrorCode.CONNECTION_NOT_AVAILABLE
    )
    assert provider.get_connection_calls == 0
    assert provider.disconnect_calls == 0
    assert "another_provider" not in str(captured.value)
