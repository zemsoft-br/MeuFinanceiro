"""Terminal connection guards on direct provider-derived persistence calls."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from threading import Event, Thread, current_thread
from time import monotonic
from uuid import UUID, uuid4

import pytest
from meufinanceiro_security.envelope import SecretCipher
from meufinanceiro_security.keyring import create_keyring
from sqlalchemy import event, func, select, text
from sqlalchemy.engine import Connection, Engine

from meufinanceiro_persistence.banking import (
    BankingIntegrationStore,
    CapabilitySnapshot,
    ConnectionConflictError,
    ConnectionNotFoundError,
    ExternalAccountSnapshot,
    ProviderConfigurationState,
    StoredCapability,
    StoredCapabilitySource,
    StoredCapabilityState,
    StoredConnectionStatus,
    StoredExternalAccountStatus,
    StoredExternalAccountType,
    StoredSyncCycleStatus,
    StoredSyncStatus,
    StoredTransactionObservationStatus,
    SyncConflictError,
    TransactionObservationSnapshot,
)
from meufinanceiro_persistence.banking_fairness_schema import sync_cycles
from meufinanceiro_persistence.banking_observation_schema import external_observations
from meufinanceiro_persistence.banking_reconciliation_schema import (
    reconciled_transactions,
)
from meufinanceiro_persistence.schema import (
    connection_capabilities,
    connections,
    external_accounts,
    sync_cursors,
)

NOW = datetime(2026, 8, 10, tzinfo=UTC)


@pytest.fixture
def store(runtime_engine: Engine) -> BankingIntegrationStore:
    return BankingIntegrationStore(runtime_engine, SecretCipher(create_keyring()))


def _context(connection: Connection, installation_id: UUID, residence_id: UUID) -> None:
    connection.execute(
        select(
            func.set_config("app.current_installation_id", str(installation_id), True),
            func.set_config("app.current_residence_id", str(residence_id), True),
        )
    )


def _setup(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
    *,
    residence_ids: tuple[UUID, ...] | None = None,
) -> tuple[UUID, UUID, UUID]:
    installation_id = uuid4()
    residence_id = residence_ids[0] if residence_ids else uuid4()
    create_canonical_residences(installation_id, residence_ids or (residence_id,))
    configuration = store.create_configuration(
        installation_id=installation_id,
        provider="pluggy",
        client_id="synthetic-client",
        client_secret="synthetic-secret",
    )
    store.set_configuration_state(
        installation_id=installation_id,
        provider="pluggy",
        expected_revision=configuration.configuration_revision,
        state=ProviderConfigurationState.ENABLED,
    )
    record = store.register_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        provider="pluggy",
        external_connection_id="synthetic-terminal-connection",
        status=StoredConnectionStatus.AVAILABLE,
        requires_user_action=False,
        last_attempt_at=NOW,
    )
    return installation_id, residence_id, record.id


def _account(account_id: str, *, name: str = "Old account") -> ExternalAccountSnapshot:
    return ExternalAccountSnapshot(
        external_account_id=account_id,
        account_type=StoredExternalAccountType.BANK,
        subtype="CHECKING_ACCOUNT",
        currency="BRL",
        status=StoredExternalAccountStatus.ACTIVE,
        observed_at=NOW,
        name=name,
    )


def _observation(
    account_id: str, resource_id: str, *, amount: str
) -> TransactionObservationSnapshot:
    return TransactionObservationSnapshot(
        external_account_id=account_id,
        external_resource_id=resource_id,
        status=StoredTransactionObservationStatus.CONFIRMED,
        effective_date=date(2026, 8, 10),
        amount=Decimal(amount),
        currency="BRL",
        observed_at=NOW,
    )


def _disconnect(
    store: BankingIntegrationStore,
    installation_id: UUID,
    residence_id: UUID,
    connection_id: UUID,
) -> None:
    assert store.finalize_connection_disconnection(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
    )


def test_account_cursor_and_cycle_writers_preserve_history_after_disconnect(
    runtime_engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id = _setup(
        store, create_canonical_residences
    )
    store.replace_external_accounts(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        snapshots=(_account("old-account"), _account("no-cursor-account")),
    )
    old_cursor = store.commit_sync_cursor(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id="old-account",
        cursor="old-cursor",
        source_window="old-window",
        committed_at=NOW,
    )
    _disconnect(store, installation_id, residence_id, connection_id)
    with runtime_engine.begin() as connection:
        _context(connection, installation_id, residence_id)
        account_history = (
            connection.execute(
                select(external_accounts).where(
                    external_accounts.c.connection_id == connection_id
                )
            )
            .mappings()
            .all()
        )

    for snapshots in (
        (_account("new-account"),),
        (_account("old-account", name="Reactivated"),),
    ):
        with pytest.raises(SyncConflictError, match="disconnected"):
            store.replace_external_accounts(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                snapshots=snapshots,
            )
    for account_id in ("old-account", "no-cursor-account"):
        with pytest.raises(SyncConflictError, match="disconnected"):
            store.commit_sync_cursor(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                external_account_id=account_id,
                cursor="new-cursor",
                source_window="new-window",
                committed_at=NOW + timedelta(minutes=1),
            )
    with pytest.raises(SyncConflictError, match="disconnected"):
        store.prepare_sync_cycle(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
            eligible_external_account_ids=("old-account",),
        )

    assert (
        store.get_sync_cursor(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
            external_account_id="old-account",
        )
        == old_cursor
    )
    with runtime_engine.begin() as connection:
        _context(connection, installation_id, residence_id)
        assert (
            connection.execute(
                select(external_accounts).where(
                    external_accounts.c.connection_id == connection_id
                )
            )
            .mappings()
            .all()
            == account_history
        )
        accounts = connection.execute(
            select(
                external_accounts.c.external_account_id,
                external_accounts.c.name,
                external_accounts.c.status,
            ).where(external_accounts.c.connection_id == connection_id)
        ).all()
        assert set(accounts) == {
            (
                "old-account",
                "Old account",
                StoredExternalAccountStatus.DISCONNECTED.value,
            ),
            (
                "no-cursor-account",
                "Old account",
                StoredExternalAccountStatus.DISCONNECTED.value,
            ),
        }
        assert connection.scalar(select(func.count()).select_from(sync_cursors)) == 1
        assert connection.scalar(select(func.count()).select_from(sync_cycles)) == 0


def test_observation_page_rejects_create_update_and_cursor_mutations(
    runtime_engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id = _setup(
        store, create_canonical_residences
    )
    store.replace_external_accounts(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        snapshots=(_account("observed-account"),),
    )
    original = _observation("observed-account", "old-resource", amount="10.00")
    store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id="observed-account",
        observations=(original,),
        cursor="old-page-cursor",
        source_window="old-window",
        committed_at=NOW,
    )
    with runtime_engine.begin() as connection:
        _context(connection, installation_id, residence_id)
        before = (
            connection.execute(
                select(external_observations).where(
                    external_observations.c.connection_id == connection_id
                )
            )
            .mappings()
            .all()
        )
        cursor_before = (
            connection.execute(
                select(sync_cursors).where(
                    sync_cursors.c.connection_id == connection_id
                )
            )
            .mappings()
            .all()
        )
    _disconnect(store, installation_id, residence_id, connection_id)
    reconciled = store.reconcile_transaction_observations(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
    )
    assert reconciled.identities_created == 1

    for observations, cursor in (
        (
            (_observation("observed-account", "new-resource", amount="20.00"),),
            "new-page-cursor",
        ),
        (
            (_observation("observed-account", "old-resource", amount="99.00"),),
            "updated-page-cursor",
        ),
        ((), None),
    ):
        with pytest.raises(SyncConflictError, match="disconnected"):
            store.apply_transaction_page(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                external_account_id="observed-account",
                observations=observations,
                cursor=cursor,
                source_window="new-window",
                committed_at=NOW + timedelta(minutes=1),
            )
    with runtime_engine.begin() as connection:
        _context(connection, installation_id, residence_id)
        assert (
            connection.execute(
                select(external_observations).where(
                    external_observations.c.connection_id == connection_id
                )
            )
            .mappings()
            .all()
            == before
        )
        assert (
            connection.execute(
                select(sync_cursors).where(
                    sync_cursors.c.connection_id == connection_id
                )
            )
            .mappings()
            .all()
            == cursor_before
        )
        assert (
            connection.scalar(select(func.count()).select_from(reconciled_transactions))
            == 1
        )


def test_prepare_cycle_cannot_reset_historical_cursor_after_disconnect(
    runtime_engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id = _setup(
        store, create_canonical_residences
    )
    store.replace_external_accounts(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        snapshots=(_account("cycle-account"),),
    )
    cursor = store.commit_sync_cursor(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id="cycle-account",
        cursor="historical-recovery",
        source_window="FULL",
        committed_at=NOW,
    )
    completed = store.prepare_sync_cycle(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        eligible_external_account_ids=(),
    )
    assert completed.cycle.status is StoredSyncCycleStatus.COMPLETED
    _disconnect(store, installation_id, residence_id, connection_id)

    with pytest.raises(SyncConflictError, match="disconnected"):
        store.prepare_sync_cycle(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
            eligible_external_account_ids=("cycle-account",),
        )
    assert (
        store.get_sync_cursor(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
            external_account_id="cycle-account",
        )
        == cursor
    )
    with runtime_engine.begin() as connection:
        _context(connection, installation_id, residence_id)
        assert connection.scalar(select(func.count()).select_from(sync_cycles)) == 1


def test_prepare_cycle_allows_running_sync_and_finish_before_disconnect(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id = _setup(
        store, create_canonical_residences
    )
    run = store.begin_manual_sync(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        idempotency_key="active-cycle-before-disconnect",
    )
    store.mark_sync_running(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        sync_run_id=run.id,
    )
    plan = store.prepare_sync_cycle(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        eligible_external_account_ids=(),
    )
    assert plan.cycle.status is StoredSyncCycleStatus.COMPLETED
    with pytest.raises(SyncConflictError, match="active banking synchronization"):
        store.finalize_connection_disconnection(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
        )
    finished = store.finish_sync(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        sync_run_id=run.id,
        status=StoredSyncStatus.CANCELLED,
        records_seen=0,
        records_applied=0,
    )
    assert finished.status is StoredSyncStatus.CANCELLED
    _disconnect(store, installation_id, residence_id, connection_id)


def test_registration_and_capabilities_cannot_resurrect_disconnected_connection(
    runtime_engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    other_residence = uuid4()
    installation_id, residence_id, connection_id = _setup(
        store, create_canonical_residences, residence_ids=(uuid4(), other_residence)
    )
    reused = store.register_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        provider="pluggy",
        external_connection_id="synthetic-terminal-connection",
        status=StoredConnectionStatus.PARTIAL,
        requires_user_action=False,
        last_attempt_at=NOW + timedelta(minutes=1),
    )
    assert reused.id == connection_id
    assert reused.status is StoredConnectionStatus.PARTIAL
    store.replace_capabilities(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        snapshots=(
            CapabilitySnapshot(
                capability=StoredCapability.TRANSACTIONS,
                state=StoredCapabilityState.SUPPORTED,
                source=StoredCapabilitySource.OBSERVATION,
                observed_at=NOW,
            ),
            CapabilitySnapshot(
                capability=StoredCapability.LOANS,
                state=StoredCapabilityState.NOT_OBSERVED,
                source=StoredCapabilitySource.OBSERVATION,
                observed_at=NOW,
            ),
        ),
    )
    _disconnect(store, installation_id, residence_id, connection_id)
    historical = store.get_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
    )
    with runtime_engine.begin() as connection:
        _context(connection, installation_id, residence_id)
        capabilities_before = (
            connection.execute(
                select(connection_capabilities).where(
                    connection_capabilities.c.connection_id == connection_id
                )
            )
            .mappings()
            .all()
        )

    with pytest.raises(
        ConnectionConflictError, match="external connection is already assigned"
    ):
        store.register_connection(
            installation_id=installation_id,
            residence_id=residence_id,
            provider="pluggy",
            external_connection_id="synthetic-terminal-connection",
            status=StoredConnectionStatus.AVAILABLE,
            requires_user_action=False,
            last_attempt_at=NOW + timedelta(days=1),
        )
    for snapshots in (
        (),
        (
            CapabilitySnapshot(
                capability=StoredCapability.TRANSACTIONS,
                state=StoredCapabilityState.REQUIRES_USER_ACTION,
                source=StoredCapabilitySource.OPERATION,
                observed_at=NOW + timedelta(days=1),
            ),
        ),
        (
            CapabilitySnapshot(
                capability=StoredCapability.INVESTMENTS,
                state=StoredCapabilityState.SUPPORTED,
                source=StoredCapabilitySource.OBSERVATION,
                observed_at=NOW + timedelta(days=1),
            ),
        ),
    ):
        with pytest.raises(SyncConflictError, match="disconnected"):
            store.replace_capabilities(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                snapshots=snapshots,
            )

    assert (
        store.get_connection(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
        )
        == historical
    )
    with runtime_engine.begin() as connection:
        _context(connection, installation_id, residence_id)
        assert (
            connection.execute(
                select(connection_capabilities).where(
                    connection_capabilities.c.connection_id == connection_id
                )
            )
            .mappings()
            .all()
            == capabilities_before
        )
    with pytest.raises(ConnectionNotFoundError):
        store.get_connection(
            installation_id=installation_id,
            residence_id=other_residence,
            connection_id=connection_id,
        )
    with pytest.raises(ConnectionNotFoundError):
        store.replace_capabilities(
            installation_id=installation_id,
            residence_id=other_residence,
            connection_id=connection_id,
            snapshots=(),
        )
    with pytest.raises(ConnectionNotFoundError):
        store.replace_external_accounts(
            installation_id=installation_id,
            residence_id=other_residence,
            connection_id=connection_id,
            snapshots=(_account("foreign-account"),),
        )
    with pytest.raises(ConnectionNotFoundError):
        store.commit_sync_cursor(
            installation_id=installation_id,
            residence_id=other_residence,
            connection_id=connection_id,
            external_account_id="foreign-account",
            cursor="foreign-cursor",
            source_window="foreign-window",
            committed_at=NOW,
        )
    with pytest.raises(ConnectionNotFoundError):
        store.apply_transaction_page(
            installation_id=installation_id,
            residence_id=other_residence,
            connection_id=connection_id,
            external_account_id="foreign-account",
            observations=(),
            cursor=None,
            source_window="foreign-window",
            committed_at=NOW,
        )
    with pytest.raises(ConnectionNotFoundError):
        store.prepare_sync_cycle(
            installation_id=installation_id,
            residence_id=other_residence,
            connection_id=connection_id,
            eligible_external_account_ids=(),
        )
    with pytest.raises(
        ConnectionConflictError, match="external connection is already assigned"
    ):
        store.register_connection(
            installation_id=installation_id,
            residence_id=other_residence,
            provider="pluggy",
            external_connection_id="synthetic-terminal-connection",
            status=StoredConnectionStatus.AVAILABLE,
            requires_user_action=False,
        )
    with runtime_engine.begin() as connection:
        _context(connection, installation_id, other_residence)
        assert connection.scalar(select(func.count()).select_from(connections)) == 0
        assert (
            connection.scalar(select(func.count()).select_from(connection_capabilities))
            == 0
        )


def test_writer_advisory_gate_serializes_disconnect_after_committed_account_write(
    engine: Engine,
    runtime_engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id = _setup(
        store, create_canonical_residences
    )
    writer_at_insert = Event()
    release_writer = Event()
    disconnect_at_gate = Event()
    writer_done = Event()
    disconnect_done = Event()
    disconnect_pid: list[int] = []
    writer_errors: list[BaseException] = []
    disconnect_errors: list[BaseException] = []
    worker_threads: dict[str, Thread] = {}

    def before_cursor_execute(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if (
            current_thread() is worker_threads.get("writer")
            and statement.startswith("INSERT INTO ")
            and "external_accounts" in statement
        ):
            writer_at_insert.set()
            if not release_writer.wait(timeout=15):
                raise RuntimeError("writer release timed out")
        if (
            current_thread() is worker_threads.get("disconnect")
            and "pg_advisory_lock(" in statement
        ):
            disconnect_pid.append(
                connection.connection.driver_connection.info.backend_pid
            )
            disconnect_at_gate.set()

    def writer() -> None:
        try:
            store.replace_external_accounts(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                snapshots=(_account("racing-account"),),
            )
        except BaseException as error:
            writer_errors.append(error)
        finally:
            writer_done.set()

    def disconnect() -> None:
        try:
            _disconnect(store, installation_id, residence_id, connection_id)
        except BaseException as error:
            disconnect_errors.append(error)
        finally:
            disconnect_done.set()

    event.listen(runtime_engine, "before_cursor_execute", before_cursor_execute)
    try:
        worker_threads["writer"] = Thread(target=writer, daemon=True)
        worker_threads["writer"].start()
        assert writer_at_insert.wait(timeout=10)
        worker_threads["disconnect"] = Thread(target=disconnect, daemon=True)
        worker_threads["disconnect"].start()
        assert disconnect_at_gate.wait(timeout=10)
        deadline = monotonic() + 10
        blocked = False
        while monotonic() < deadline:
            with engine.connect() as observer:
                blocked = bool(
                    observer.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                        {"pid": disconnect_pid[0]},
                    )
                )
            if blocked:
                break
            disconnect_done.wait(timeout=0.02)
        assert blocked
    finally:
        release_writer.set()
        for worker in worker_threads.values():
            worker.join(timeout=10)
        event.remove(runtime_engine, "before_cursor_execute", before_cursor_execute)

    assert writer_done.is_set() and disconnect_done.is_set()
    assert writer_errors == [] and disconnect_errors == []
    assert (
        store.get_connection(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
        ).status
        is StoredConnectionStatus.DISCONNECTED
    )
    with runtime_engine.begin() as connection:
        _context(connection, installation_id, residence_id)
        assert (
            connection.scalar(
                select(external_accounts.c.status).where(
                    external_accounts.c.connection_id == connection_id
                )
            )
            == StoredExternalAccountStatus.DISCONNECTED.value
        )


def test_register_upsert_observes_terminal_row_finalized_concurrently(
    runtime_engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id = _setup(
        store, create_canonical_residences
    )
    writer_at_lookup = Event()
    release_lookup = Event()
    writer_done = Event()
    errors: list[BaseException] = []
    writer_thread: Thread

    def pause_lookup(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if (
            current_thread() is writer_thread
            and statement.startswith("SELECT ")
            and "external_connection_id" in statement
            and "connections.id" in statement
        ):
            writer_at_lookup.set()
            if not release_lookup.wait(timeout=15):
                raise RuntimeError("registration lookup release timed out")

    def register() -> None:
        try:
            store.register_connection(
                installation_id=installation_id,
                residence_id=residence_id,
                provider="pluggy",
                external_connection_id="synthetic-terminal-connection",
                status=StoredConnectionStatus.AVAILABLE,
                requires_user_action=False,
                last_attempt_at=NOW + timedelta(days=1),
            )
        except BaseException as error:
            errors.append(error)
        finally:
            writer_done.set()

    writer_thread = Thread(target=register, daemon=True)
    event.listen(runtime_engine, "before_cursor_execute", pause_lookup)
    try:
        writer_thread.start()
        assert writer_at_lookup.wait(timeout=10)
        _disconnect(store, installation_id, residence_id, connection_id)
        terminal = store.get_connection(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
        )
    finally:
        release_lookup.set()
        writer_thread.join(timeout=15)
        event.remove(runtime_engine, "before_cursor_execute", pause_lookup)

    assert writer_done.is_set()
    assert len(errors) == 1
    assert isinstance(errors[0], ConnectionConflictError)
    assert (
        store.get_connection(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
        )
        == terminal
    )
    assert terminal.status is StoredConnectionStatus.DISCONNECTED
    assert terminal.disconnected_at is not None
    assert terminal.last_attempt_at == NOW


def test_disconnect_provider_io_blocks_new_provider_derived_write(
    engine: Engine,
    runtime_engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id = _setup(
        store, create_canonical_residences
    )
    callback_entered = Event()
    release_callback = Event()
    writer_sql_entered = Event()
    writer_done = Event()
    disconnect_done = Event()
    writer_pid: list[int] = []
    writer_errors: list[BaseException] = []
    disconnect_errors: list[BaseException] = []
    workers: dict[str, Thread] = {}

    def provider_callback() -> None:
        callback_entered.set()
        if not release_callback.wait(timeout=15):
            raise RuntimeError("provider callback release timed out")

    def disconnect() -> None:
        try:
            assert store.execute_connection_disconnection(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                operation=provider_callback,
            )
        except BaseException as error:
            disconnect_errors.append(error)
        finally:
            disconnect_done.set()

    def writer() -> None:
        try:
            store.replace_external_accounts(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                snapshots=(_account("provider-io-race-account"),),
            )
        except BaseException as error:
            writer_errors.append(error)
        finally:
            writer_done.set()

    def record_writer_pid(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if current_thread() is workers.get("writer") and "set_config" in statement:
            writer_pid.append(connection.connection.driver_connection.info.backend_pid)
            writer_sql_entered.set()

    event.listen(runtime_engine, "before_cursor_execute", record_writer_pid)
    blocked = False
    try:
        workers["disconnect"] = Thread(target=disconnect, daemon=True)
        workers["disconnect"].start()
        assert callback_entered.wait(timeout=10)
        assert (
            store.get_connection(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
            ).status
            is StoredConnectionStatus.AVAILABLE
        )

        workers["writer"] = Thread(target=writer, daemon=True)
        workers["writer"].start()
        assert writer_sql_entered.wait(timeout=10)
        deadline = monotonic() + 10
        while monotonic() < deadline and not writer_done.is_set():
            with engine.connect() as observer:
                blocked = bool(
                    observer.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                        {"pid": writer_pid[0]},
                    )
                )
            if blocked:
                break
            writer_done.wait(timeout=0.02)
        with runtime_engine.begin() as connection:
            _context(connection, installation_id, residence_id)
            accounts_during_callback = connection.scalar(
                select(func.count()).select_from(external_accounts)
            )
        assert blocked, (
            "writer was not blocked during provider I/O: "
            f"writer_done={writer_done.is_set()}, "
            f"accounts_written={accounts_during_callback}"
        )
        assert not writer_done.is_set()
        assert accounts_during_callback == 0
    finally:
        release_callback.set()
        for worker in workers.values():
            worker.join(timeout=15)
        event.remove(runtime_engine, "before_cursor_execute", record_writer_pid)

    assert disconnect_done.is_set() and writer_done.is_set()
    assert disconnect_errors == []
    assert len(writer_errors) == 1
    assert isinstance(writer_errors[0], SyncConflictError)
    assert "disconnected" in str(writer_errors[0])
    with runtime_engine.begin() as connection:
        _context(connection, installation_id, residence_id)
        assert (
            connection.scalar(select(func.count()).select_from(external_accounts)) == 0
        )


def test_register_reuse_waits_for_disconnect_provider_io(
    engine: Engine,
    runtime_engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id = _setup(
        store, create_canonical_residences
    )
    callback_entered = Event()
    release_callback = Event()
    registration_sql_entered = Event()
    registration_done = Event()
    disconnect_done = Event()
    registration_pid: list[int] = []
    registration_errors: list[BaseException] = []
    disconnect_errors: list[BaseException] = []
    workers: dict[str, Thread] = {}

    def provider_callback() -> None:
        callback_entered.set()
        if not release_callback.wait(timeout=15):
            raise RuntimeError("provider callback release timed out")

    def disconnect() -> None:
        try:
            assert store.execute_connection_disconnection(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=connection_id,
                operation=provider_callback,
            )
        except BaseException as error:
            disconnect_errors.append(error)
        finally:
            disconnect_done.set()

    def register() -> None:
        try:
            store.register_connection(
                installation_id=installation_id,
                residence_id=residence_id,
                provider="pluggy",
                external_connection_id="synthetic-terminal-connection",
                status=StoredConnectionStatus.PARTIAL,
                requires_user_action=False,
                last_attempt_at=NOW + timedelta(days=1),
            )
        except BaseException as error:
            registration_errors.append(error)
        finally:
            registration_done.set()

    def record_registration_pid(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if current_thread() is workers.get("register") and "set_config" in statement:
            registration_pid.append(
                connection.connection.driver_connection.info.backend_pid
            )
            registration_sql_entered.set()

    event.listen(runtime_engine, "before_cursor_execute", record_registration_pid)
    blocked = False
    try:
        workers["disconnect"] = Thread(target=disconnect, daemon=True)
        workers["disconnect"].start()
        assert callback_entered.wait(timeout=10)
        workers["register"] = Thread(target=register, daemon=True)
        workers["register"].start()
        assert registration_sql_entered.wait(timeout=10)
        deadline = monotonic() + 10
        while monotonic() < deadline and not registration_done.is_set():
            with engine.connect() as observer:
                blocked = bool(
                    observer.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                        {"pid": registration_pid[0]},
                    )
                )
            if blocked:
                break
            registration_done.wait(timeout=0.02)
        during_callback = store.get_connection(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
        )
        assert blocked, (
            "registration was not blocked during provider I/O: "
            f"registration_done={registration_done.is_set()}, "
            f"status={during_callback.status.value}, "
            f"last_attempt_at={during_callback.last_attempt_at}"
        )
        assert during_callback.status is StoredConnectionStatus.AVAILABLE
        assert during_callback.last_attempt_at == NOW
    finally:
        release_callback.set()
        for worker in workers.values():
            worker.join(timeout=15)
        event.remove(runtime_engine, "before_cursor_execute", record_registration_pid)

    assert disconnect_done.is_set() and registration_done.is_set()
    assert disconnect_errors == []
    assert len(registration_errors) == 1
    assert isinstance(registration_errors[0], ConnectionConflictError)
    terminal = store.get_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
    )
    assert terminal.status is StoredConnectionStatus.DISCONNECTED
    assert terminal.last_attempt_at == NOW


def test_concurrent_first_registration_cannot_skip_disconnect_gate(
    engine: Engine,
    runtime_engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, _ = _setup(store, create_canonical_residences)
    first_inserted = Event()
    release_first = Event()
    first_done = Event()
    second_at_insert = Event()
    release_second = Event()
    second_done = Event()
    callback_entered = Event()
    release_callback = Event()
    disconnect_done = Event()
    first_ids: list[UUID] = []
    second_pid: list[int] = []
    first_errors: list[BaseException] = []
    second_errors: list[BaseException] = []
    disconnect_errors: list[BaseException] = []
    workers: dict[str, Thread] = {}

    def before_cursor_execute(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if (
            current_thread() is workers.get("second")
            and statement.startswith("INSERT INTO ")
            and "connections" in statement
        ):
            second_pid.append(connection.connection.driver_connection.info.backend_pid)
            second_at_insert.set()
            if not release_second.wait(timeout=15):
                raise RuntimeError("second registration release timed out")

    def after_cursor_execute(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if (
            current_thread() is workers.get("first")
            and statement.startswith("INSERT INTO ")
            and "connections" in statement
        ):
            first_inserted.set()
            if not release_first.wait(timeout=15):
                raise RuntimeError("first registration release timed out")

    def register_first() -> None:
        try:
            record = store.register_connection(
                installation_id=installation_id,
                residence_id=residence_id,
                provider="pluggy",
                external_connection_id="synthetic-colliding-new-connection",
                status=StoredConnectionStatus.AVAILABLE,
                requires_user_action=False,
                last_attempt_at=NOW,
            )
            first_ids.append(record.id)
        except BaseException as error:
            first_errors.append(error)
        finally:
            first_done.set()

    def register_second() -> None:
        try:
            store.register_connection(
                installation_id=installation_id,
                residence_id=residence_id,
                provider="pluggy",
                external_connection_id="synthetic-colliding-new-connection",
                status=StoredConnectionStatus.PARTIAL,
                requires_user_action=False,
                last_attempt_at=NOW + timedelta(days=1),
            )
        except BaseException as error:
            second_errors.append(error)
        finally:
            second_done.set()

    def provider_callback() -> None:
        callback_entered.set()
        if not release_callback.wait(timeout=15):
            raise RuntimeError("provider callback release timed out")

    def disconnect() -> None:
        try:
            assert store.execute_connection_disconnection(
                installation_id=installation_id,
                residence_id=residence_id,
                connection_id=first_ids[0],
                operation=provider_callback,
            )
        except BaseException as error:
            disconnect_errors.append(error)
        finally:
            disconnect_done.set()

    event.listen(runtime_engine, "before_cursor_execute", before_cursor_execute)
    event.listen(runtime_engine, "after_cursor_execute", after_cursor_execute)
    blocked = False
    try:
        workers["first"] = Thread(target=register_first, daemon=True)
        workers["first"].start()
        assert first_inserted.wait(timeout=10)
        workers["second"] = Thread(target=register_second, daemon=True)
        workers["second"].start()
        assert second_at_insert.wait(timeout=10)
        release_first.set()
        assert first_done.wait(timeout=10)
        assert first_errors == [] and len(first_ids) == 1

        workers["disconnect"] = Thread(target=disconnect, daemon=True)
        workers["disconnect"].start()
        assert callback_entered.wait(timeout=10)
        release_second.set()
        deadline = monotonic() + 10
        while monotonic() < deadline and not second_done.is_set():
            with engine.connect() as observer:
                blocked = bool(
                    observer.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                        {"pid": second_pid[0]},
                    )
                )
            if blocked:
                break
            second_done.wait(timeout=0.02)
        during_callback = store.get_connection(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=first_ids[0],
        )
        assert blocked, (
            "second registration skipped the disconnect gate: "
            f"second_done={second_done.is_set()}, "
            f"status={during_callback.status.value}"
        )
        assert during_callback.status is StoredConnectionStatus.AVAILABLE
        assert during_callback.last_attempt_at == NOW
    finally:
        release_first.set()
        release_second.set()
        release_callback.set()
        for worker in workers.values():
            worker.join(timeout=15)
        event.remove(runtime_engine, "before_cursor_execute", before_cursor_execute)
        event.remove(runtime_engine, "after_cursor_execute", after_cursor_execute)

    assert second_done.is_set() and disconnect_done.is_set()
    assert disconnect_errors == []
    assert len(second_errors) == 1
    assert isinstance(second_errors[0], ConnectionConflictError)
    terminal = store.get_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=first_ids[0],
    )
    assert terminal.status is StoredConnectionStatus.DISCONNECTED
    assert terminal.last_attempt_at == NOW
