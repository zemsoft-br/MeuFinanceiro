from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from uuid import UUID, uuid4

import pytest
from meufinanceiro_security.envelope import SecretCipher
from meufinanceiro_security.keyring import create_keyring
from sqlalchemy import func, select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.banking import (
    BankingIntegrationStore,
    ConnectionNotFoundError,
    ExternalAccountNotFoundError,
    ExternalAccountSnapshot,
    ProviderConfigurationState,
    StoredConnectionStatus,
    StoredExternalAccountStatus,
    StoredExternalAccountType,
    StoredSyncErrorCategory,
    StoredSyncStatus,
    SyncConflictError,
    SyncTransitionError,
)
from meufinanceiro_persistence.schema import (
    external_accounts,
    sync_cursors,
    sync_runs,
)

NOW = datetime(2026, 8, 8, 3, 30, tzinfo=UTC)


@pytest.fixture
def cipher() -> SecretCipher:
    return SecretCipher(create_keyring())


@pytest.fixture
def store(runtime_engine: Engine, cipher: SecretCipher) -> BankingIntegrationStore:
    return BankingIntegrationStore(runtime_engine, cipher)


def _set_context(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
) -> None:
    connection.execute(
        select(
            func.set_config(
                "app.current_installation_id",
                str(installation_id),
                True,
            )
        )
    )
    connection.execute(
        select(
            func.set_config(
                "app.current_residence_id",
                str(residence_id),
                True,
            )
        )
    )


def _enable_configuration(
    store: BankingIntegrationStore,
    installation_id: UUID,
) -> None:
    configured = store.create_configuration(
        installation_id=installation_id,
        provider="pluggy",
        client_id="synthetic-client-id",
        client_secret="synthetic-client-secret",
    )
    store.set_configuration_state(
        installation_id=installation_id,
        provider="pluggy",
        expected_revision=configured.configuration_revision,
        state=ProviderConfigurationState.ENABLED,
    )


def _register_connection(
    store: BankingIntegrationStore,
    *,
    installation_id: UUID,
    residence_id: UUID,
    external_connection_id: str,
    status: StoredConnectionStatus = StoredConnectionStatus.AVAILABLE,
) -> UUID:
    disconnected_at = NOW if status is StoredConnectionStatus.DISCONNECTED else None
    record = store.register_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        provider="pluggy",
        external_connection_id=external_connection_id,
        status=status,
        requires_user_action=False,
        disconnected_at=disconnected_at,
    )
    return record.id


def _account(
    external_account_id: str,
    *,
    observed_at: datetime = NOW,
    status: StoredExternalAccountStatus = StoredExternalAccountStatus.ACTIVE,
    name: str = "Conta sintética",
) -> ExternalAccountSnapshot:
    return ExternalAccountSnapshot(
        external_account_id=external_account_id,
        account_type=StoredExternalAccountType.BANK,
        subtype="CHECKING_ACCOUNT",
        currency="BRL",
        status=status,
        observed_at=observed_at,
        name=name,
        number_mask="1234",
    )


def test_manual_sync_is_idempotent_and_single_flight(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    create_canonical_residences(installation_id, (residence_id,))
    _enable_configuration(store, installation_id)
    connection_id = _register_connection(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
        external_connection_id="synthetic-item-a",
    )

    first = store.begin_manual_sync(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        idempotency_key="manual-sync-001",
    )
    duplicate = store.begin_manual_sync(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        idempotency_key="manual-sync-001",
    )

    assert duplicate.id == first.id
    assert first.status is StoredSyncStatus.REQUESTED
    assert "manual-sync-001" not in repr(first)

    with pytest.raises(SyncConflictError, match="already active"):
        store.begin_manual_sync(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
            idempotency_key="manual-sync-002",
        )

    running = store.mark_sync_running(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        sync_run_id=first.id,
    )
    assert running.status is StoredSyncStatus.RUNNING
    assert running.attempt_count == 1
    assert running.started_at is not None

    with pytest.raises(SyncTransitionError, match="transition is invalid"):
        store.mark_sync_running(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
            sync_run_id=first.id,
        )

    completed = store.finish_sync(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        sync_run_id=first.id,
        status=StoredSyncStatus.SUCCEEDED,
        records_seen=4,
        records_applied=4,
    )
    assert completed.status is StoredSyncStatus.SUCCEEDED
    assert completed.finished_at is not None

    next_run = store.begin_manual_sync(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        idempotency_key="manual-sync-002",
    )
    assert next_run.id != first.id


def test_disconnected_connection_and_cross_residence_scope_fail_closed(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_a = uuid4()
    residence_b = uuid4()
    create_canonical_residences(installation_id, (residence_a, residence_b))
    _enable_configuration(store, installation_id)
    connection_id = _register_connection(
        store,
        installation_id=installation_id,
        residence_id=residence_a,
        external_connection_id="synthetic-item-disconnected",
        status=StoredConnectionStatus.DISCONNECTED,
    )

    with pytest.raises(SyncConflictError, match="disconnected"):
        store.begin_manual_sync(
            installation_id=installation_id,
            residence_id=residence_a,
            connection_id=connection_id,
            idempotency_key="manual-sync-disconnected",
        )

    with pytest.raises(ConnectionNotFoundError):
        store.begin_manual_sync(
            installation_id=installation_id,
            residence_id=residence_b,
            connection_id=connection_id,
            idempotency_key="manual-sync-cross-residence",
        )


def test_sync_completion_validates_transitions_and_diagnostics(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    create_canonical_residences(installation_id, (residence_id,))
    _enable_configuration(store, installation_id)
    connection_id = _register_connection(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
        external_connection_id="synthetic-item-diagnostics",
    )
    run = store.begin_manual_sync(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        idempotency_key="manual-sync-diagnostics",
    )

    with pytest.raises(ValueError, match="terminal"):
        store.finish_sync(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
            sync_run_id=run.id,
            status=StoredSyncStatus.RUNNING,
            records_seen=0,
            records_applied=0,
        )

    failed = store.finish_sync(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        sync_run_id=run.id,
        status=StoredSyncStatus.FAILED,
        error_category=StoredSyncErrorCategory.TEMPORARILY_UNAVAILABLE,
        provider_reason_code="TEMPORARY",
        http_status=503,
        retry_window_bucket="short",
        records_seen=3,
        records_applied=1,
    )
    assert failed.error_category is StoredSyncErrorCategory.TEMPORARILY_UNAVAILABLE
    assert failed.http_status == 503
    assert failed.records_seen == 3
    assert failed.records_applied == 1


def test_external_account_snapshot_is_idempotent_minimized_and_monotonic(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    create_canonical_residences(installation_id, (residence_id,))
    _enable_configuration(store, installation_id)
    connection_id = _register_connection(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
        external_connection_id="synthetic-item-accounts",
    )

    first = store.replace_external_accounts(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        snapshots=(_account("synthetic-account-a"),),
    )
    assert len(first) == 1
    assert first[0].number_mask == "1234"
    assert "synthetic-account-a" not in repr(first[0])

    newer = NOW + timedelta(minutes=5)
    updated = store.replace_external_accounts(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        snapshots=(
            _account(
                "synthetic-account-a",
                observed_at=newer,
                status=StoredExternalAccountStatus.UNAVAILABLE,
                name="Conta atualizada",
            ),
            _account("synthetic-account-b", observed_at=newer),
        ),
    )
    assert len(updated) == 2
    account_a = next(
        account
        for account in updated
        if account.external_account_id == "synthetic-account-a"
    )
    assert account_a.last_seen_at == newer
    assert account_a.status is StoredExternalAccountStatus.UNAVAILABLE

    stale = store.replace_external_accounts(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        snapshots=(
            _account(
                "synthetic-account-a",
                observed_at=NOW - timedelta(minutes=5),
                status=StoredExternalAccountStatus.ACTIVE,
                name="Stale value",
            ),
        ),
    )
    stale_a = next(
        account
        for account in stale
        if account.external_account_id == "synthetic-account-a"
    )
    assert stale_a.last_seen_at == newer
    assert stale_a.status is StoredExternalAccountStatus.UNAVAILABLE
    assert len(stale) == 2

    with pytest.raises(ValueError, match="full numeric account number"):
        _account("synthetic-account-invalid", name="Conta").__class__(
            external_account_id="synthetic-account-invalid",
            account_type=StoredExternalAccountType.BANK,
            subtype="CHECKING_ACCOUNT",
            currency="BRL",
            status=StoredExternalAccountStatus.ACTIVE,
            observed_at=NOW,
            number_mask="123456789",
        )


def test_cursor_is_scoped_idempotent_and_never_moves_backwards(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    create_canonical_residences(installation_id, (residence_id,))
    _enable_configuration(store, installation_id)
    connection_a = _register_connection(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
        external_connection_id="synthetic-item-cursor-a",
    )
    connection_b = _register_connection(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
        external_connection_id="synthetic-item-cursor-b",
    )
    store.replace_external_accounts(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_a,
        snapshots=(_account("synthetic-account-cursor-a"),),
    )
    store.replace_external_accounts(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_b,
        snapshots=(_account("synthetic-account-cursor-b"),),
    )

    assert (
        store.get_sync_cursor(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_a,
            external_account_id="synthetic-account-cursor-a",
        )
        is None
    )

    committed = store.commit_sync_cursor(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_a,
        external_account_id="synthetic-account-cursor-a",
        cursor="opaque-cursor-001",
        source_window="initial-window",
        committed_at=NOW,
    )
    same = store.commit_sync_cursor(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_a,
        external_account_id="synthetic-account-cursor-a",
        cursor="opaque-cursor-001",
        source_window="initial-window",
        committed_at=NOW,
    )
    assert same.id == committed.id
    assert "opaque-cursor-001" not in repr(committed)
    assert "synthetic-account-cursor-a" not in repr(committed)

    with pytest.raises(SyncConflictError, match="inconsistent"):
        store.commit_sync_cursor(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_a,
            external_account_id="synthetic-account-cursor-a",
            cursor="opaque-cursor-other",
            source_window="initial-window",
            committed_at=NOW,
        )

    later = store.commit_sync_cursor(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_a,
        external_account_id="synthetic-account-cursor-a",
        cursor="opaque-cursor-002",
        source_window="next-window",
        committed_at=NOW + timedelta(minutes=1),
    )
    assert later.cursor == "opaque-cursor-002"

    with pytest.raises(SyncConflictError, match="stale"):
        store.commit_sync_cursor(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_a,
            external_account_id="synthetic-account-cursor-a",
            cursor="opaque-cursor-stale",
            source_window="stale-window",
            committed_at=NOW - timedelta(minutes=1),
        )

    with pytest.raises(ExternalAccountNotFoundError):
        store.commit_sync_cursor(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_a,
            external_account_id="synthetic-account-cursor-b",
            cursor="opaque-cursor-cross",
            source_window="cross-window",
            committed_at=NOW + timedelta(minutes=2),
        )


def test_runtime_rls_hides_new_tables_without_or_with_wrong_residence_context(
    runtime_engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_a = uuid4()
    residence_b = uuid4()
    create_canonical_residences(installation_id, (residence_a, residence_b))
    _enable_configuration(store, installation_id)
    connection_id = _register_connection(
        store,
        installation_id=installation_id,
        residence_id=residence_a,
        external_connection_id="synthetic-item-rls",
    )
    run = store.begin_manual_sync(
        installation_id=installation_id,
        residence_id=residence_a,
        connection_id=connection_id,
        idempotency_key="manual-sync-rls",
    )
    store.finish_sync(
        installation_id=installation_id,
        residence_id=residence_a,
        connection_id=connection_id,
        sync_run_id=run.id,
        status=StoredSyncStatus.CANCELLED,
        records_seen=0,
        records_applied=0,
    )
    store.replace_external_accounts(
        installation_id=installation_id,
        residence_id=residence_a,
        connection_id=connection_id,
        snapshots=(_account("synthetic-account-rls"),),
    )
    store.commit_sync_cursor(
        installation_id=installation_id,
        residence_id=residence_a,
        connection_id=connection_id,
        external_account_id="synthetic-account-rls",
        cursor="opaque-cursor-rls",
        source_window="rls-window",
        committed_at=NOW,
    )

    with runtime_engine.begin() as connection:
        assert connection.scalar(select(func.count()).select_from(sync_runs)) == 0
        assert (
            connection.scalar(select(func.count()).select_from(external_accounts)) == 0
        )
        assert connection.scalar(select(func.count()).select_from(sync_cursors)) == 0

    with runtime_engine.begin() as connection:
        _set_context(
            connection,
            installation_id=installation_id,
            residence_id=residence_b,
        )
        assert connection.scalar(select(func.count()).select_from(sync_runs)) == 0
        assert (
            connection.scalar(select(func.count()).select_from(external_accounts)) == 0
        )
        assert connection.scalar(select(func.count()).select_from(sync_cursors)) == 0

    with runtime_engine.begin() as connection:
        _set_context(
            connection,
            installation_id=installation_id,
            residence_id=residence_a,
        )
        assert connection.scalar(select(func.count()).select_from(sync_runs)) == 1
        assert (
            connection.scalar(select(func.count()).select_from(external_accounts)) == 1
        )
        assert connection.scalar(select(func.count()).select_from(sync_cursors)) == 1


def test_disconnection_execution_is_idempotent_and_preserves_sync_history(
    runtime_engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    create_canonical_residences(installation_id, (residence_id,))
    _enable_configuration(store, installation_id)

    connection_record = store.register_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        provider="pluggy",
        external_connection_id="synthetic-item-disconnection-history",
        status=StoredConnectionStatus.RATE_LIMITED,
        requires_user_action=False,
        next_refresh_allowed_at=NOW + timedelta(minutes=30),
        provider_reason_code="RATE_LIMITED",
    )
    connection_id = connection_record.id

    store.replace_external_accounts(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        snapshots=(_account("synthetic-account-disconnection"),),
    )

    sync_run = store.begin_manual_sync(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        idempotency_key="manual-sync-before-disconnection",
    )
    store.finish_sync(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        sync_run_id=sync_run.id,
        status=StoredSyncStatus.CANCELLED,
        records_seen=0,
        records_applied=0,
    )

    cursor = store.commit_sync_cursor(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id="synthetic-account-disconnection",
        cursor="opaque-cursor-before-disconnection",
        source_window="historical-window",
        committed_at=NOW,
    )

    operation_calls = 0

    def disconnect_provider() -> None:
        nonlocal operation_calls
        operation_calls += 1

    executed = store.execute_connection_disconnection(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        operation=disconnect_provider,
    )

    assert executed is True
    assert operation_calls == 1

    disconnected = store.get_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
    )

    assert disconnected.status is StoredConnectionStatus.DISCONNECTED
    assert disconnected.requires_user_action is False
    assert disconnected.disconnected_at is not None
    assert disconnected.next_refresh_allowed_at is None
    assert disconnected.provider_reason_code is None

    first_disconnected_at = disconnected.disconnected_at

    with runtime_engine.begin() as connection:
        _set_context(
            connection,
            installation_id=installation_id,
            residence_id=residence_id,
        )

        account_status = connection.scalar(
            select(external_accounts.c.status).where(
                external_accounts.c.residence_id == residence_id,
                external_accounts.c.connection_id == connection_id,
                external_accounts.c.external_account_id
                == "synthetic-account-disconnection",
            )
        )
        persisted_run = (
            connection.execute(
                select(
                    sync_runs.c.id,
                    sync_runs.c.status,
                ).where(sync_runs.c.id == sync_run.id)
            )
            .mappings()
            .one()
        )
        persisted_cursor = (
            connection.execute(
                select(
                    sync_cursors.c.id,
                    sync_cursors.c.cursor,
                ).where(sync_cursors.c.id == cursor.id)
            )
            .mappings()
            .one()
        )

    assert account_status == StoredExternalAccountStatus.DISCONNECTED.value
    assert persisted_run["id"] == sync_run.id
    assert persisted_run["status"] == StoredSyncStatus.CANCELLED.value
    assert persisted_cursor["id"] == cursor.id
    assert persisted_cursor["cursor"] == "opaque-cursor-before-disconnection"

    replayed = store.execute_connection_disconnection(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        operation=disconnect_provider,
    )

    assert replayed is False
    assert operation_calls == 1

    replayed_connection = store.get_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
    )

    assert replayed_connection.disconnected_at == first_disconnected_at


def test_disconnection_execution_rejects_active_sync_and_wrong_residence(
    runtime_engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_a = uuid4()
    residence_b = uuid4()

    create_canonical_residences(
        installation_id,
        (residence_a, residence_b),
    )
    _enable_configuration(store, installation_id)

    connection_id = _register_connection(
        store,
        installation_id=installation_id,
        residence_id=residence_a,
        external_connection_id="synthetic-item-disconnection-active-sync",
    )

    store.replace_external_accounts(
        installation_id=installation_id,
        residence_id=residence_a,
        connection_id=connection_id,
        snapshots=(_account("synthetic-account-active-sync"),),
    )

    sync_run = store.begin_manual_sync(
        installation_id=installation_id,
        residence_id=residence_a,
        connection_id=connection_id,
        idempotency_key="manual-sync-blocks-disconnection",
    )

    provider_called = False

    def unexpected_provider_call() -> None:
        nonlocal provider_called
        provider_called = True

    with pytest.raises(
        SyncConflictError,
        match="active banking synchronization",
    ):
        store.execute_connection_disconnection(
            installation_id=installation_id,
            residence_id=residence_a,
            connection_id=connection_id,
            operation=unexpected_provider_call,
        )

    assert provider_called is False

    unchanged = store.get_connection(
        installation_id=installation_id,
        residence_id=residence_a,
        connection_id=connection_id,
    )
    assert unchanged.status is StoredConnectionStatus.AVAILABLE
    assert unchanged.disconnected_at is None

    with runtime_engine.begin() as connection:
        _set_context(
            connection,
            installation_id=installation_id,
            residence_id=residence_a,
        )
        account_status = connection.scalar(
            select(external_accounts.c.status).where(
                external_accounts.c.residence_id == residence_a,
                external_accounts.c.connection_id == connection_id,
                external_accounts.c.external_account_id
                == "synthetic-account-active-sync",
            )
        )

    assert account_status == StoredExternalAccountStatus.ACTIVE.value

    with pytest.raises(ConnectionNotFoundError):
        store.execute_connection_disconnection(
            installation_id=installation_id,
            residence_id=residence_b,
            connection_id=connection_id,
            operation=unexpected_provider_call,
        )

    assert provider_called is False

    store.finish_sync(
        installation_id=installation_id,
        residence_id=residence_a,
        connection_id=connection_id,
        sync_run_id=sync_run.id,
        status=StoredSyncStatus.CANCELLED,
        records_seen=0,
        records_applied=0,
    )

    executed = store.execute_connection_disconnection(
        installation_id=installation_id,
        residence_id=residence_a,
        connection_id=connection_id,
        operation=lambda: None,
    )

    assert executed is True


def test_disconnection_advisory_guard_prevents_sync_start_without_open_transaction(
    engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()

    create_canonical_residences(installation_id, (residence_id,))
    _enable_configuration(store, installation_id)

    connection_id = _register_connection(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
        external_connection_id="synthetic-item-disconnection-race",
    )

    operation_started = Event()
    release_operation = Event()
    disconnection_finished = Event()
    sync_attempt_started = Event()
    sync_finished = Event()

    disconnection_errors: list[BaseException] = []
    sync_errors: list[BaseException] = []

    def external_operation() -> None:
        # The connection-level advisory lock must remain granted while the
        # provider callback runs, but its PostgreSQL session must not have an
        # open transaction.
        with engine.connect() as observer:
            guard_sessions = (
                observer.execute(
                    text(
                        """
                        SELECT activity.state, activity.xact_start
                        FROM pg_locks AS locks
                        JOIN pg_stat_activity AS activity
                          ON activity.pid = locks.pid
                        WHERE locks.locktype = 'advisory'
                          AND locks.granted
                          AND activity.datname = current_database()
                          AND locks.pid <> pg_backend_pid()
                        """
                    )
                )
                .mappings()
                .all()
            )

        assert len(guard_sessions) == 1
        assert guard_sessions[0]["state"] == "idle"
        assert guard_sessions[0]["xact_start"] is None

        operation_started.set()

        if not release_operation.wait(timeout=10):
            raise RuntimeError("test timed out waiting to release provider operation")

    def disconnect_worker() -> None:
        try:
            store.execute_connection_disconnection(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                operation=external_operation,
            )
        except BaseException as error:
            disconnection_errors.append(error)
        finally:
            disconnection_finished.set()

    def sync_worker() -> None:
        sync_attempt_started.set()
        try:
            store.begin_manual_sync(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                idempotency_key="sync-racing-disconnection",
            )
        except BaseException as error:
            sync_errors.append(error)
        finally:
            sync_finished.set()

    disconnect_thread = Thread(target=disconnect_worker, daemon=True)
    disconnect_thread.start()

    assert operation_started.wait(timeout=10)

    sync_thread = Thread(target=sync_worker, daemon=True)
    sync_thread.start()

    assert sync_attempt_started.wait(timeout=10)

    # begin_manual_sync acquires the same connection advisory gate and
    # therefore cannot complete while the provider operation owns the guard.
    assert sync_finished.wait(timeout=0.5) is False

    release_operation.set()

    assert disconnection_finished.wait(timeout=10)
    assert sync_finished.wait(timeout=10)

    disconnect_thread.join(timeout=1)
    sync_thread.join(timeout=1)

    assert disconnection_errors == []
    assert len(sync_errors) == 1
    assert isinstance(sync_errors[0], SyncConflictError)
    assert "disconnected" in str(sync_errors[0])

    connection = store.get_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
    )
    assert connection.status is StoredConnectionStatus.DISCONNECTED


def test_disconnection_provider_failure_rolls_back_local_state(
    runtime_engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()

    create_canonical_residences(installation_id, (residence_id,))
    _enable_configuration(store, installation_id)

    connection = store.register_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        provider="pluggy",
        external_connection_id="synthetic-item-provider-failure",
        status=StoredConnectionStatus.RATE_LIMITED,
        requires_user_action=False,
        next_refresh_allowed_at=NOW + timedelta(minutes=15),
        provider_reason_code="RATE_LIMITED",
    )

    store.replace_external_accounts(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection.id,
        snapshots=(_account("synthetic-account-provider-failure"),),
    )

    def provider_failure() -> None:
        raise RuntimeError("synthetic provider failure")

    with pytest.raises(RuntimeError, match="synthetic provider failure"):
        store.execute_connection_disconnection(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection.id,
            operation=provider_failure,
        )

    unchanged = store.get_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection.id,
    )

    assert unchanged.status is StoredConnectionStatus.RATE_LIMITED
    assert unchanged.disconnected_at is None
    assert unchanged.requires_user_action is False
    assert unchanged.next_refresh_allowed_at == NOW + timedelta(minutes=15)
    assert unchanged.provider_reason_code == "RATE_LIMITED"

    with runtime_engine.begin() as database:
        _set_context(
            database,
            installation_id=installation_id,
            residence_id=residence_id,
        )
        account_status = database.scalar(
            select(external_accounts.c.status).where(
                external_accounts.c.residence_id == residence_id,
                external_accounts.c.connection_id == connection.id,
                external_accounts.c.external_account_id
                == "synthetic-account-provider-failure",
            )
        )

    assert account_status == StoredExternalAccountStatus.ACTIVE.value


def test_finalize_connection_disconnection_is_explicit_and_idempotent(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()

    create_canonical_residences(installation_id, (residence_id,))
    _enable_configuration(store, installation_id)

    connection_id = _register_connection(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
        external_connection_id="synthetic-item-explicit-finalize",
    )

    store.replace_external_accounts(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        snapshots=(_account("synthetic-account-explicit-finalize"),),
    )

    first = store.finalize_connection_disconnection(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
    )
    second = store.finalize_connection_disconnection(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
    )

    assert first is True
    assert second is False

    disconnected = store.get_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
    )

    assert disconnected.status is StoredConnectionStatus.DISCONNECTED
    assert disconnected.disconnected_at is not None


def test_two_disconnection_attempts_serialize_to_one_external_operation(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()

    create_canonical_residences(installation_id, (residence_id,))
    _enable_configuration(store, installation_id)

    connection_id = _register_connection(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
        external_connection_id="synthetic-item-double-disconnect",
    )

    first_operation_started = Event()
    release_first_operation = Event()
    second_attempt_started = Event()
    second_attempt_finished = Event()
    second_operation_called = Event()

    results: list[bool] = []
    errors: list[BaseException] = []

    def first_operation() -> None:
        first_operation_started.set()

        if not release_first_operation.wait(timeout=10):
            raise RuntimeError("test timed out releasing first disconnect")

    def second_operation() -> None:
        second_operation_called.set()

    def first_worker() -> None:
        try:
            result = store.execute_connection_disconnection(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                operation=first_operation,
            )
            results.append(result)
        except BaseException as error:
            errors.append(error)

    def second_worker() -> None:
        second_attempt_started.set()

        try:
            result = store.execute_connection_disconnection(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                operation=second_operation,
            )
            results.append(result)
        except BaseException as error:
            errors.append(error)
        finally:
            second_attempt_finished.set()

    first_thread = Thread(target=first_worker, daemon=True)
    first_thread.start()

    assert first_operation_started.wait(timeout=10)

    second_thread = Thread(target=second_worker, daemon=True)
    second_thread.start()

    assert second_attempt_started.wait(timeout=10)

    # The second attempt must be waiting on the same advisory lock.
    assert second_attempt_finished.wait(timeout=0.5) is False
    assert second_operation_called.is_set() is False

    release_first_operation.set()

    first_thread.join(timeout=10)
    second_thread.join(timeout=10)

    assert first_thread.is_alive() is False
    assert second_thread.is_alive() is False
    assert errors == []
    assert sorted(results) == [False, True]
    assert second_operation_called.is_set() is False

    disconnected = store.get_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
    )

    assert disconnected.status is StoredConnectionStatus.DISCONNECTED


def test_advisory_guard_invalidates_session_when_commit_fails_after_lock() -> None:
    from meufinanceiro_persistence.banking_sync_store import (
        _connection_advisory_guard,
    )

    class SyntheticConnection:
        def __init__(self) -> None:
            self.execute_calls = 0
            self.commit_calls = 0
            self.invalidated = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            del exc_type, exc, traceback
            return False

        def execute(self, statement):
            del statement
            self.execute_calls += 1
            return object()

        def commit(self) -> None:
            self.commit_calls += 1
            raise DBAPIError(
                "COMMIT",
                {},
                RuntimeError("synthetic commit failure"),
                False,
            )

        def invalidate(self) -> None:
            self.invalidated = True

        def in_transaction(self) -> bool:
            return False

        def rollback(self) -> None:
            raise AssertionError("rollback must not run after invalidation")

        def scalar(self, statement):
            del statement
            raise AssertionError("unlock must not use invalidated session")

    class SyntheticEngine:
        def __init__(self, connection: SyntheticConnection) -> None:
            self.connection = connection

        def connect(self) -> SyntheticConnection:
            return self.connection

    connection = SyntheticConnection()
    engine = SyntheticEngine(connection)

    with pytest.raises(DBAPIError, match="synthetic commit failure"):
        with _connection_advisory_guard(engine, uuid4()):
            raise AssertionError("guard body must not execute")

    assert connection.execute_calls == 1
    assert connection.commit_calls == 1
    assert connection.invalidated is True
