from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from meufinanceiro_banking import (
    BankingProviderError,
    ConnectionState,
    ConnectionStatus,
    FakeBankingProvider,
    ProviderErrorCategory,
)
from meufinanceiro_persistence import (
    BankingConnectionRecord,
    BankingPersistenceError,
    ConnectionConflictError,
    StoredConnectionStatus,
)

from meufinanceiro_banking_sync import (
    BankingConnectionDisconnectionService,
    BankingDisconnectErrorCode,
    BankingDisconnectExecutionError,
)

_NOW = datetime(2026, 8, 18, 8, 0, tzinfo=UTC)


def _local_record(*, status: StoredConnectionStatus = StoredConnectionStatus.AVAILABLE) -> BankingConnectionRecord:
    disconnected_at = _NOW if status is StoredConnectionStatus.DISCONNECTED else None
    return BankingConnectionRecord(
        id=uuid4(),
        installation_id=uuid4(),
        residence_id=uuid4(),
        provider="fake",
        external_connection_id="external-sensitive-connection",
        status=status,
        requires_user_action=False,
        last_successful_sync_at=None,
        last_attempt_at=None,
        next_refresh_allowed_at=None,
        consent_expires_at=None,
        provider_reason_code=None,
        disconnected_at=disconnected_at,
        created_at=_NOW,
        updated_at=_NOW,
    )


class _Store:
    def __init__(self, record: BankingConnectionRecord) -> None:
        self.record = record
        self.finalize_failures = 0
        self.busy = False
        self.lock_entries = 0

    @contextmanager
    def hold_connection_disconnection_lock(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        connection_id: UUID,
    ) -> Iterator[None]:
        assert installation_id == self.record.installation_id
        assert residence_id == self.record.residence_id
        assert connection_id == self.record.id
        assert isinstance(operator_id, UUID)
        self.lock_entries += 1
        yield

    def prepare_connection_disconnection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        connection_id: UUID,
    ) -> BankingConnectionRecord:
        assert installation_id == self.record.installation_id
        assert residence_id == self.record.residence_id
        assert connection_id == self.record.id
        assert isinstance(operator_id, UUID)
        if self.busy:
            raise ConnectionConflictError("synthetic busy connection")
        return self.record

    def finalize_connection_disconnection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        connection_id: UUID,
    ) -> BankingConnectionRecord:
        assert installation_id == self.record.installation_id
        assert residence_id == self.record.residence_id
        assert connection_id == self.record.id
        assert isinstance(operator_id, UUID)
        if self.finalize_failures:
            self.finalize_failures -= 1
            raise BankingPersistenceError("synthetic local finalization failure")
        self.record = replace(
            self.record,
            status=StoredConnectionStatus.DISCONNECTED,
            requires_user_action=False,
            provider_reason_code=None,
            disconnected_at=_NOW,
            updated_at=_NOW,
        )
        return self.record


class _CountingProvider(FakeBankingProvider):
    def __init__(self) -> None:
        super().__init__()
        self.get_calls = 0
        self.disconnect_calls = 0
        self.fail_get = False
        self.fail_disconnect = False

    def get_connection(self, external_connection_id: str) -> ConnectionState:
        self.get_calls += 1
        if self.fail_get:
            raise BankingProviderError(
                ProviderErrorCategory.TEMPORARILY_UNAVAILABLE,
                retryable=True,
                safe_message="synthetic provider read failure",
            )
        return super().get_connection(external_connection_id)

    def disconnect(self, external_connection_id: str, actor_id: str) -> None:
        self.disconnect_calls += 1
        if self.fail_disconnect:
            raise BankingProviderError(
                ProviderErrorCategory.UNSUPPORTED,
                retryable=False,
                safe_message="synthetic disconnect unsupported",
            )
        super().disconnect(external_connection_id, actor_id)


class _WrongProvider(_CountingProvider):
    @property
    def provider_name(self) -> str:
        return "different"


def _provider_for(
    record: BankingConnectionRecord,
    *,
    status: ConnectionStatus = ConnectionStatus.AVAILABLE,
) -> _CountingProvider:
    provider = _CountingProvider()
    provider.seed_connection(
        ConnectionState(
            external_connection_id=record.external_connection_id,
            status=status,
            capabilities=(),
        ),
        residence_id=str(record.residence_id),
    )
    return provider


def _run(
    store: _Store,
    provider: FakeBankingProvider,
    *,
    operator_id: UUID | None = None,
):
    return BankingConnectionDisconnectionService(
        store=store,
        provider=provider,
    ).disconnect_connection(
        installation_id=store.record.installation_id,
        residence_id=store.record.residence_id,
        operator_id=operator_id or uuid4(),
        connection_id=store.record.id,
    )


def test_disconnect_mutates_provider_once_then_finalizes_local_state() -> None:
    record = _local_record()
    store = _Store(record)
    provider = _provider_for(record)

    result = _run(store, provider)

    assert result.status is StoredConnectionStatus.DISCONNECTED
    assert result.provider_mutation_performed is True
    assert result.recovered_from_provider_state is False
    assert store.record.status is StoredConnectionStatus.DISCONNECTED
    assert provider.disconnect_calls == 1
    assert store.lock_entries == 1
    assert "external-sensitive-connection" not in repr(result)


def test_local_disconnected_replay_performs_no_provider_io() -> None:
    record = _local_record(status=StoredConnectionStatus.DISCONNECTED)
    store = _Store(record)
    provider = _provider_for(record)

    result = _run(store, provider)

    assert result.provider_mutation_performed is False
    assert result.recovered_from_provider_state is False
    assert provider.get_calls == 0
    assert provider.disconnect_calls == 0


def test_remote_disconnected_recovers_local_without_second_mutation() -> None:
    record = _local_record()
    store = _Store(record)
    provider = _provider_for(record, status=ConnectionStatus.DISCONNECTED)

    result = _run(store, provider)

    assert result.provider_mutation_performed is False
    assert result.recovered_from_provider_state is True
    assert store.record.status is StoredConnectionStatus.DISCONNECTED
    assert provider.disconnect_calls == 0


def test_provider_read_failure_leaves_local_state_unchanged() -> None:
    record = _local_record()
    store = _Store(record)
    provider = _provider_for(record)
    provider.fail_get = True

    with pytest.raises(BankingDisconnectExecutionError) as captured:
        _run(store, provider)

    assert captured.value.code is BankingDisconnectErrorCode.PROVIDER_REJECTED
    assert store.record.status is StoredConnectionStatus.AVAILABLE
    assert provider.disconnect_calls == 0
    assert "external-sensitive-connection" not in str(captured.value)


def test_provider_disconnect_failure_leaves_local_state_unchanged() -> None:
    record = _local_record()
    store = _Store(record)
    provider = _provider_for(record)
    provider.fail_disconnect = True

    with pytest.raises(BankingDisconnectExecutionError) as captured:
        _run(store, provider)

    assert captured.value.code is BankingDisconnectErrorCode.PROVIDER_REJECTED
    assert store.record.status is StoredConnectionStatus.AVAILABLE
    assert provider.disconnect_calls == 1


def test_local_failure_after_external_success_is_recovered_without_retrying_provider() -> None:
    record = _local_record()
    store = _Store(record)
    store.finalize_failures = 1
    provider = _provider_for(record)

    with pytest.raises(BankingDisconnectExecutionError) as captured:
        _run(store, provider)
    assert captured.value.code is BankingDisconnectErrorCode.LOCAL_FINALIZATION_PENDING
    assert store.record.status is StoredConnectionStatus.AVAILABLE
    assert provider.disconnect_calls == 1
    assert provider.get_connection(record.external_connection_id).status is ConnectionStatus.DISCONNECTED

    result = _run(store, provider)

    assert result.recovered_from_provider_state is True
    assert result.provider_mutation_performed is False
    assert store.record.status is StoredConnectionStatus.DISCONNECTED
    assert provider.disconnect_calls == 1


def test_busy_local_connection_fails_before_provider_io() -> None:
    record = _local_record()
    store = _Store(record)
    store.busy = True
    provider = _provider_for(record)

    with pytest.raises(BankingDisconnectExecutionError) as captured:
        _run(store, provider)

    assert captured.value.code is BankingDisconnectErrorCode.BUSY
    assert provider.get_calls == 0
    assert provider.disconnect_calls == 0


def test_provider_mismatch_fails_before_external_identifier_is_used() -> None:
    record = _local_record()
    store = _Store(record)
    provider = _WrongProvider()

    with pytest.raises(BankingDisconnectExecutionError) as captured:
        _run(store, provider)

    assert captured.value.code is BankingDisconnectErrorCode.PROVIDER_MISMATCH
    assert provider.get_calls == 0
    assert provider.disconnect_calls == 0
    assert "external-sensitive-connection" not in str(captured.value)
