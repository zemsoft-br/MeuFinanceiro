from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from meufinanceiro_security.envelope import SecretCipher
from meufinanceiro_security.keyring import create_keyring
from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine

from meufinanceiro_persistence import (
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
    StoredSyncStatus,
    StoredTransactionObservationStatus,
    SyncConflictError,
    TransactionObservationSnapshot,
)
from meufinanceiro_persistence.banking_observation_schema import external_observations
from meufinanceiro_persistence.banking_reconciliation_schema import (
    reconciled_transactions,
)
from meufinanceiro_persistence.schema import (
    connection_capabilities,
    external_accounts,
    household_memberships,
    sync_runs,
)

_NOW = datetime(2026, 8, 18, 8, 30, tzinfo=UTC)


def _store(runtime_engine: Engine) -> BankingIntegrationStore:
    return BankingIntegrationStore(runtime_engine, SecretCipher(create_keyring()))


def _operator_id(engine: Engine, residence_id: UUID) -> UUID:
    with engine.begin() as connection:
        value = connection.scalar(
            select(household_memberships.c.operator_id).where(
                household_memberships.c.residence_id == residence_id,
                household_memberships.c.status == "active",
            )
        )
    assert isinstance(value, UUID)
    return value


def _setup_connection(
    store: BankingIntegrationStore,
    *,
    installation_id: UUID,
    residence_id: UUID,
) -> UUID:
    configuration = store.create_configuration(
        installation_id=installation_id,
        provider="fake",
        client_id="synthetic-client-id",
        client_secret="synthetic-client-secret",
    )
    store.set_configuration_state(
        installation_id=installation_id,
        provider="fake",
        expected_revision=configuration.configuration_revision,
        state=ProviderConfigurationState.ENABLED,
    )
    connection = store.register_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        provider="fake",
        external_connection_id="synthetic-external-connection",
        status=StoredConnectionStatus.AVAILABLE,
        requires_user_action=False,
        next_refresh_allowed_at=_NOW,
        provider_reason_code="SYNTHETIC_REASON",
    )
    store.replace_capabilities(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection.id,
        snapshots=(
            CapabilitySnapshot(
                capability=StoredCapability.DISCONNECT,
                state=StoredCapabilityState.SUPPORTED,
                source=StoredCapabilitySource.CONTRACT,
                observed_at=_NOW,
            ),
        ),
    )
    store.replace_external_accounts(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection.id,
        snapshots=(
            ExternalAccountSnapshot(
                external_account_id="synthetic-account",
                account_type=StoredExternalAccountType.BANK,
                subtype="CHECKING_ACCOUNT",
                currency="BRL",
                status=StoredExternalAccountStatus.ACTIVE,
                observed_at=_NOW,
                number_mask="1234",
            ),
        ),
    )
    return connection.id


def test_finalize_disconnect_is_atomic_idempotent_and_preserves_history(
    runtime_engine: Engine,
    engine: Engine,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    create_canonical_residences(installation_id, (residence_id,))
    operator_id = _operator_id(engine, residence_id)
    store = _store(runtime_engine)
    connection_id = _setup_connection(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
    )

    sync_run = store.begin_manual_sync(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        idempotency_key="disconnect-history-sync",
    )
    running = store.mark_sync_running(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        sync_run_id=sync_run.id,
    )
    assert running.status is StoredSyncStatus.RUNNING
    store.finish_sync(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        sync_run_id=sync_run.id,
        status=StoredSyncStatus.SUCCEEDED,
        records_seen=0,
        records_applied=0,
    )

    store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id="synthetic-account",
        observations=(
            TransactionObservationSnapshot(
                external_account_id="synthetic-account",
                external_resource_id="synthetic-transaction",
                status=StoredTransactionObservationStatus.CONFIRMED,
                provider_updated_at=_NOW,
                effective_date=date(2026, 8, 18),
                amount=Decimal("-42.50"),
                currency="BRL",
                description="Synthetic retained observation",
                category="synthetic",
                observed_at=_NOW,
            ),
        ),
        cursor=None,
        source_window="FULL",
        committed_at=_NOW,
    )
    reconciliation = store.reconcile_transaction_observations(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
    )
    assert reconciliation.processed_count == 1

    with store.hold_connection_disconnection_lock(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
        connection_id=connection_id,
    ):
        prepared = store.prepare_connection_disconnection(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            connection_id=connection_id,
        )
        assert prepared.status is StoredConnectionStatus.AVAILABLE
        finalized = store.finalize_connection_disconnection(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            connection_id=connection_id,
        )

    assert finalized.status is StoredConnectionStatus.DISCONNECTED
    assert finalized.requires_user_action is False
    assert finalized.disconnected_at is not None
    assert finalized.next_refresh_allowed_at is None
    assert finalized.provider_reason_code is None

    disconnected_at = finalized.disconnected_at
    replay = store.finalize_connection_disconnection(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
        connection_id=connection_id,
    )
    assert replay.status is StoredConnectionStatus.DISCONNECTED
    assert replay.disconnected_at == disconnected_at

    with engine.begin() as connection:
        assert connection.scalar(
            select(func.count()).select_from(connection_capabilities)
        ) == 1
        assert connection.scalar(select(func.count()).select_from(sync_runs)) == 1
        assert connection.scalar(
            select(func.count()).select_from(external_observations)
        ) == 1
        assert connection.scalar(
            select(func.count()).select_from(reconciled_transactions)
        ) == 1
        statuses = connection.scalars(
            select(external_accounts.c.status).where(
                external_accounts.c.connection_id == connection_id
            )
        ).all()
    assert statuses == [StoredExternalAccountStatus.DISCONNECTED.value]

    with pytest.raises(SyncConflictError, match="disconnected"):
        store.begin_manual_sync(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
            idempotency_key="sync-after-disconnect",
        )


def test_active_sync_blocks_disconnect_before_local_state_changes(
    runtime_engine: Engine,
    engine: Engine,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    create_canonical_residences(installation_id, (residence_id,))
    operator_id = _operator_id(engine, residence_id)
    store = _store(runtime_engine)
    connection_id = _setup_connection(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
    )
    store.begin_manual_sync(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        idempotency_key="active-before-disconnect",
    )

    with store.hold_connection_disconnection_lock(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
        connection_id=connection_id,
    ):
        with pytest.raises(ConnectionConflictError, match="active synchronization"):
            store.prepare_connection_disconnection(
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=operator_id,
                connection_id=connection_id,
            )

    current = store.get_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
    )
    assert current.status is StoredConnectionStatus.AVAILABLE
    assert current.disconnected_at is None


def test_inactive_membership_and_cross_residence_fail_closed(
    runtime_engine: Engine,
    engine: Engine,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_a = uuid4()
    residence_b = uuid4()
    create_canonical_residences(installation_id, (residence_a, residence_b))
    operator_id = _operator_id(engine, residence_a)
    store = _store(runtime_engine)
    connection_id = _setup_connection(
        store,
        installation_id=installation_id,
        residence_id=residence_a,
    )

    with pytest.raises(ConnectionNotFoundError):
        with store.hold_connection_disconnection_lock(
            installation_id=installation_id,
            residence_id=residence_b,
            operator_id=operator_id,
            connection_id=connection_id,
        ):
            pass

    with engine.begin() as connection:
        connection.execute(
            update(household_memberships)
            .where(
                household_memberships.c.residence_id == residence_a,
                household_memberships.c.operator_id == operator_id,
            )
            .values(status="disabled", is_primary=False)
        )

    with pytest.raises(ConnectionNotFoundError):
        with store.hold_connection_disconnection_lock(
            installation_id=installation_id,
            residence_id=residence_a,
            operator_id=operator_id,
            connection_id=connection_id,
        ):
            pass
