from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from threading import Barrier, Event, Lock
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
    BankingDisconnectResult,
)

_NOW = datetime(2026, 8, 18, 8, 0, tzinfo=UTC)


def _local_record(
    *,
    status: StoredConnectionStatus = StoredConnectionStatus.AVAILABLE,
) -> BankingConnectionRecord:
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
        self.transaction_entries = 0

    @contextmanager
    def connection_disconnection_transaction(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        connection_id: UUID,
    ) -> Iterator[BankingConnectionRecord]:
        assert installation_id == self.record.installation_id
        assert residence_id == self.record.residence_id
        assert connection_id == self.record.id
        assert isinstance(operator_id, UUID)
        if self.busy:
            raise ConnectionConflictError("synthetic busy connection")
        self.transaction_entries += 1
        original = self.record
        try:
            yield original
        except Exception:
            raise
        else:
            if original.status is not StoredConnectionStatus.DISCONNECTED:
                if self.finalize_failures:
                    self.finalize_failures -= 1
                    raise BankingPersistenceError(
                        "synthetic local finalization failure"
                    )
                self.record = replace(
                    original,
                    status=StoredConnectionStatus.DISCONNECTED,
                    requires_user_action=False,
                    provider_reason_code=None,
                    disconnected_at=_NOW,
                    updated_at=_NOW,
                )


class _SerializingStore(_Store):
    def __init__(self, record: BankingConnectionRecord) -> None:
        super().__init__(record)
        self._operation_lock = Lock()
        self._attempt_guard = Lock()
        self.lock_attempts = 0
        self.second_attempted = Event()

    @contextmanager
    def connection_disconnection_transaction(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        connection_id: UUID,
    ) -> Iterator[BankingConnectionRecord]:
        with self._attempt_guard:
            self.lock_attempts += 1
            if self.lock_attempts >= 2:
                self.second_attempted.set()
        with self._operation_lock:
            with super().connection_disconnection_transaction(
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=operator_id,
                connection_id=connection_id,
            ) as record:
                yield record


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


class _BlockingProvider(_CountingProvider):
    def __init__(self) -> None:
        super().__init__()
        self.disconnect_entered = Event()
        self.release_disconnect = Event()

    def disconnect(self, external_connection_id: str, actor_id: str) -> None:
        self.disconnect_calls += 1
        self.disconnect_entered.set()
        if not self.release_disconnect.wait(timeout=5):
            raise AssertionError("synthetic disconnect release was not signaled")
        FakeBankingProvider.disconnect(self, external_connection_id, actor_id)


class _UnexpectedFailureProvider(_CountingProvider):
    def get_connection(self, external_connection_id: str) -> ConnectionState:
        raise RuntimeError(f"unexpected provider detail: {external_connection_id}")


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
) -> BankingDisconnectResult:
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
    assert store.transaction_entries == 1
    assert "external-sensitive-connection" not in repr(result)


def test_concurrent_disconnects_serialize_to_one_provider_mutation() -> None:
    record = _local_record()
    store = _SerializingStore(record)
    provider = _BlockingProvider()
    provider.seed_connection(
        ConnectionState(
            external_connection_id=record.external_connection_id,
            status=ConnectionStatus.AVAILABLE,
            capabilities=(),
        ),
        residence_id=str(record.residence_id),
    )
    start = Barrier(3)

    def worker() -> BankingDisconnectResult:
        start.wait()
        return _run(store, provider)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(worker)
        second = pool.submit(worker)
        start.wait()
        assert provider.disconnect_entered.wait(timeout=5)
        assert store.second_attempted.wait(timeout=5)
        assert provider.disconnect_calls == 1
        provider.release_disconnect.set()
        results = (first.result(timeout=5), second.result(timeout=5))

    assert provider.disconnect_calls == 1
    assert sum(item.provider_mutation_performed for item in results) == 1
    assert store.record.status is StoredConnectionStatus.DISCONNECTED


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


def test_unexpected_provider_failure_is_sanitized_as_internal() -> None:
    record = _local_record()
    store = _Store(record)
    provider = _UnexpectedFailureProvider()

    with pytest.raises(BankingDisconnectExecutionError) as captured:
        _run(store, provider)

    assert captured.value.code is BankingDisconnectErrorCode.INTERNAL
    assert store.record.status is StoredConnectionStatus.AVAILABLE
    assert "external-sensitive-connection" not in str(captured.value)
    assert "unexpected provider detail" not in str(captured.value)


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


def test_local_failure_after_external_success_is_recovered_without_retry() -> None:
    record = _local_record()
    store = _Store(record)
    store.finalize_failures = 1
    provider = _provider_for(record)

    with pytest.raises(BankingDisconnectExecutionError) as captured:
        _run(store, provider)
    assert (
        captured.value.code
        is BankingDisconnectErrorCode.LOCAL_FINALIZATION_PENDING
    )
    assert store.record.status is StoredConnectionStatus.AVAILABLE
    assert provider.disconnect_calls == 1
    remote = provider.get_connection(record.external_connection_id)
    assert remote.status is ConnectionStatus.DISCONNECTED

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
