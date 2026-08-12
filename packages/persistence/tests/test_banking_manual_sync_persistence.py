from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from meufinanceiro_security.envelope import SecretCipher
from meufinanceiro_security.keyring import create_keyring
from sqlalchemy import func, select
from sqlalchemy.engine import Connection, Engine

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
