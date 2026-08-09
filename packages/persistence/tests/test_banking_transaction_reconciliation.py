from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from meufinanceiro_security.envelope import SecretCipher
from meufinanceiro_security.keyring import create_keyring
from sqlalchemy import func, select, update
from sqlalchemy.engine import Connection, Engine

from meufinanceiro_persistence import (
    BankingIntegrationStore,
    ConnectionNotFoundError,
    ExternalAccountSnapshot,
    ProviderConfigurationState,
    StoredConnectionStatus,
    StoredExternalAccountStatus,
    StoredExternalAccountType,
    StoredTransactionObservationStatus,
    TransactionObservationSnapshot,
    TransactionReconciliationConflictError,
)
from meufinanceiro_persistence.banking_observation_schema import external_observations
from meufinanceiro_persistence.banking_reconciliation_schema import (
    reconciled_transaction_sources,
    reconciled_transactions,
)

NOW = datetime(2026, 8, 9, 22, 30, tzinfo=UTC)


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
            ),
            func.set_config(
                "app.current_residence_id",
                str(residence_id),
                True,
            ),
        )
    )


def _enable_configuration(
    store: BankingIntegrationStore,
    *,
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
    account_id: str,
) -> UUID:
    connection = store.register_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        provider="pluggy",
        external_connection_id=external_connection_id,
        status=StoredConnectionStatus.AVAILABLE,
        requires_user_action=False,
    )
    store.replace_external_accounts(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection.id,
        snapshots=(
            ExternalAccountSnapshot(
                external_account_id=account_id,
                account_type=StoredExternalAccountType.BANK,
                subtype="CHECKING_ACCOUNT",
                currency="BRL",
                status=StoredExternalAccountStatus.ACTIVE,
                observed_at=NOW,
                number_mask="1234",
            ),
        ),
    )
    return connection.id


def _setup(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
    *,
    account_id: str = "reconciliation-account",
) -> tuple[UUID, UUID, UUID, str]:
    installation_id = uuid4()
    residence_id = uuid4()
    create_canonical_residences(installation_id, (residence_id,))
    _enable_configuration(store, installation_id=installation_id)
    connection_id = _register_connection(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
        external_connection_id="synthetic-reconciliation-connection",
        account_id=account_id,
    )
    return installation_id, residence_id, connection_id, account_id


def _observation(
    *,
    account_id: str,
    status: StoredTransactionObservationStatus,
    observed_at: datetime,
    external_resource_id: str | None,
    amount: str = "10.00",
    description: str = "Synthetic transaction",
) -> TransactionObservationSnapshot:
    return TransactionObservationSnapshot(
        external_account_id=account_id,
        external_resource_id=external_resource_id,
        status=status,
        provider_updated_at=observed_at,
        effective_date=date(2026, 8, 9),
        amount=Decimal(amount),
        currency="BRL",
        description=description,
        category="synthetic",
        observed_at=observed_at,
    )


def _apply(
    store: BankingIntegrationStore,
    *,
    installation_id: UUID,
    residence_id: UUID,
    connection_id: UUID,
    account_id: str,
    observations: tuple[TransactionObservationSnapshot, ...],
    committed_at: datetime,
) -> None:
    store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=account_id,
        observations=observations,
        cursor=None,
        source_window="FULL",
        committed_at=committed_at,
    )


def test_provider_identity_updates_same_canonical_row_across_status_and_payload_changes(
    engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id, account_id = _setup(
        store,
        create_canonical_residences,
    )
    provider_id = "provider-transaction-stable-id"

    pending_at = NOW + timedelta(seconds=1)
    _apply(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        account_id=account_id,
        observations=(
            _observation(
                account_id=account_id,
                status=StoredTransactionObservationStatus.PENDING,
                observed_at=pending_at,
                external_resource_id=provider_id,
            ),
        ),
        committed_at=pending_at,
    )
    created = store.reconcile_transaction_observations(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
    )
    assert created.observations_seen == 1
    assert created.identities_created == 1
    assert created.identities_updated == 0
    assert created.identities_unchanged == 0
    assert not created.has_more

    with engine.begin() as connection:
        first = (
            connection.execute(select(reconciled_transactions))
            .mappings()
            .one()
        )
    canonical_id = first["id"]
    assert first["status"] == StoredTransactionObservationStatus.PENDING.value
    assert first["identity_kind"] == "PROVIDER_ID"

    confirmed_at = NOW + timedelta(seconds=2)
    _apply(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        account_id=account_id,
        observations=(
            _observation(
                account_id=account_id,
                status=StoredTransactionObservationStatus.CONFIRMED,
                observed_at=confirmed_at,
                external_resource_id=provider_id,
                amount="11.25",
                description="Changed synthetic payload",
            ),
        ),
        committed_at=confirmed_at,
    )
    updated = store.reconcile_transaction_observations(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
    )
    assert updated.observations_seen == 1
    assert updated.identities_created == 0
    assert updated.identities_updated == 1

    with engine.begin() as connection:
        rows = connection.execute(select(reconciled_transactions)).mappings().all()
    assert len(rows) == 1
    assert rows[0]["id"] == canonical_id
    assert rows[0]["status"] == StoredTransactionObservationStatus.CONFIRMED.value

    replay = store.reconcile_transaction_observations(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
    )
    assert replay.observations_seen == 0
    assert replay.identities_created == 0
    assert replay.identities_updated == 0
    assert replay.identities_unchanged == 0

    deleted_at = NOW + timedelta(seconds=3)
    _apply(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        account_id=account_id,
        observations=(
            _observation(
                account_id=account_id,
                status=StoredTransactionObservationStatus.DELETED,
                observed_at=deleted_at,
                external_resource_id=provider_id,
                amount="11.25",
                description="Changed synthetic payload",
            ),
        ),
        committed_at=deleted_at,
    )
    deleted = store.reconcile_transaction_observations(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
    )
    assert deleted.identities_updated == 1
    with engine.begin() as connection:
        final_status = connection.scalar(
            select(reconciled_transactions.c.status).where(
                reconciled_transactions.c.id == canonical_id
            )
        )
    assert final_status == StoredTransactionObservationStatus.DELETED.value


def test_absence_never_infers_deleted_state(
    engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id, account_id = _setup(
        store,
        create_canonical_residences,
    )
    observed_at = NOW + timedelta(seconds=1)
    _apply(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        account_id=account_id,
        observations=(
            _observation(
                account_id=account_id,
                status=StoredTransactionObservationStatus.CONFIRMED,
                observed_at=observed_at,
                external_resource_id="provider-present-once",
            ),
        ),
        committed_at=observed_at,
    )
    store.reconcile_transaction_observations(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
    )

    result = store.reconcile_transaction_observations(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
    )
    assert result.observations_seen == 0
    with engine.begin() as connection:
        status = connection.scalar(select(reconciled_transactions.c.status))
    assert status == StoredTransactionObservationStatus.CONFIRMED.value


def test_fingerprint_fallback_stays_isolated_from_provider_identity(
    engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id, account_id = _setup(
        store,
        create_canonical_residences,
    )
    observed_at = NOW + timedelta(seconds=1)
    _apply(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        account_id=account_id,
        observations=(
            _observation(
                account_id=account_id,
                status=StoredTransactionObservationStatus.INFERRED,
                observed_at=observed_at,
                external_resource_id=None,
                amount="10.00",
                description="Inferred A",
            ),
            _observation(
                account_id=account_id,
                status=StoredTransactionObservationStatus.INFERRED,
                observed_at=observed_at,
                external_resource_id=None,
                amount="10.00",
                description="Inferred B",
            ),
            _observation(
                account_id=account_id,
                status=StoredTransactionObservationStatus.CONFIRMED,
                observed_at=observed_at,
                external_resource_id="provider-id-same-financial-shape",
                amount="10.00",
                description="Inferred A",
            ),
        ),
        committed_at=observed_at,
    )

    result = store.reconcile_transaction_observations(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
    )
    assert result.observations_seen == 3
    assert result.identities_created == 3

    with engine.begin() as connection:
        kinds = connection.execute(
            select(reconciled_transactions.c.identity_kind)
        ).scalars().all()
    assert sorted(kinds) == ["FINGERPRINT", "FINGERPRINT", "PROVIDER_ID"]


def test_reconciliation_is_bounded_and_resumes_from_local_dirty_state(
    engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id, account_id = _setup(
        store,
        create_canonical_residences,
    )
    observed_at = NOW + timedelta(seconds=1)
    observations = tuple(
        _observation(
            account_id=account_id,
            status=StoredTransactionObservationStatus.CONFIRMED,
            observed_at=observed_at,
            external_resource_id=f"provider-bounded-{index}",
        )
        for index in range(3)
    )
    _apply(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        account_id=account_id,
        observations=observations,
        committed_at=observed_at,
    )

    first = store.reconcile_transaction_observations(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        limit=2,
    )
    assert first.observations_seen == 2
    assert first.identities_created == 2
    assert first.has_more

    second = store.reconcile_transaction_observations(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        limit=2,
    )
    assert second.observations_seen == 1
    assert second.identities_created == 1
    assert not second.has_more

    final = store.reconcile_transaction_observations(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        limit=2,
    )
    assert final.observations_seen == 0
    assert not final.has_more
    with engine.begin() as connection:
        assert (
            connection.scalar(
                select(func.count()).select_from(reconciled_transactions)
            )
            == 3
        )
        assert (
            connection.scalar(
                select(func.count()).select_from(reconciled_transaction_sources)
            )
            == 3
        )


def test_same_timestamp_incompatible_canonical_state_fails_closed(
    engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id, account_id = _setup(
        store,
        create_canonical_residences,
    )
    observed_at = NOW + timedelta(seconds=1)
    _apply(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        account_id=account_id,
        observations=(
            _observation(
                account_id=account_id,
                status=StoredTransactionObservationStatus.PENDING,
                observed_at=observed_at,
                external_resource_id="provider-tie-conflict",
            ),
        ),
        committed_at=observed_at,
    )
    store.reconcile_transaction_observations(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
    )

    with engine.begin() as connection:
        observation_id = connection.scalar(select(external_observations.c.id))
        target_id = connection.scalar(select(reconciled_transactions.c.id))
        assert observation_id is not None
        assert target_id is not None
        connection.execute(
            update(reconciled_transactions)
            .where(reconciled_transactions.c.id == target_id)
            .values(status=StoredTransactionObservationStatus.CONFIRMED.value)
        )
        connection.execute(
            update(external_observations)
            .where(external_observations.c.id == observation_id)
            .values(updated_at=NOW + timedelta(seconds=5))
        )

    with pytest.raises(TransactionReconciliationConflictError):
        store.reconcile_transaction_observations(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
        )

    with engine.begin() as connection:
        target_status = connection.scalar(
            select(reconciled_transactions.c.status).where(
                reconciled_transactions.c.id == target_id
            )
        )
        tracked_updated_at = connection.scalar(
            select(reconciled_transaction_sources.c.observation_updated_at).where(
                reconciled_transaction_sources.c.source_observation_id == observation_id
            )
        )
        observation_updated_at = connection.scalar(
            select(external_observations.c.updated_at).where(
                external_observations.c.id == observation_id
            )
        )
    assert target_status == StoredTransactionObservationStatus.CONFIRMED.value
    assert tracked_updated_at < observation_updated_at


def test_connection_scope_is_local_and_cross_residence_is_rejected(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_a = uuid4()
    residence_b = uuid4()
    create_canonical_residences(installation_id, (residence_a, residence_b))
    _enable_configuration(store, installation_id=installation_id)
    connection_id = _register_connection(
        store,
        installation_id=installation_id,
        residence_id=residence_a,
        external_connection_id="synthetic-reconciliation-scope",
        account_id="scope-account",
    )

    with pytest.raises(ConnectionNotFoundError):
        store.reconcile_transaction_observations(
            installation_id=installation_id,
            residence_id=residence_b,
            connection_id=connection_id,
        )


def test_reconciliation_tables_are_hidden_without_matching_residence_context(
    runtime_engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_a = uuid4()
    residence_b = uuid4()
    create_canonical_residences(installation_id, (residence_a, residence_b))
    _enable_configuration(store, installation_id=installation_id)
    connection_id = _register_connection(
        store,
        installation_id=installation_id,
        residence_id=residence_a,
        external_connection_id="synthetic-reconciliation-rls",
        account_id="rls-account",
    )
    observed_at = NOW + timedelta(seconds=1)
    _apply(
        store,
        installation_id=installation_id,
        residence_id=residence_a,
        connection_id=connection_id,
        account_id="rls-account",
        observations=(
            _observation(
                account_id="rls-account",
                status=StoredTransactionObservationStatus.CONFIRMED,
                observed_at=observed_at,
                external_resource_id="provider-rls",
            ),
        ),
        committed_at=observed_at,
    )
    store.reconcile_transaction_observations(
        installation_id=installation_id,
        residence_id=residence_a,
        connection_id=connection_id,
    )

    with runtime_engine.begin() as connection:
        assert (
            connection.scalar(
                select(func.count()).select_from(reconciled_transactions)
            )
            == 0
        )
        assert (
            connection.scalar(
                select(func.count()).select_from(reconciled_transaction_sources)
            )
            == 0
        )

    with runtime_engine.begin() as connection:
        _set_context(
            connection,
            installation_id=installation_id,
            residence_id=residence_b,
        )
        assert (
            connection.scalar(
                select(func.count()).select_from(reconciled_transactions)
            )
            == 0
        )
        assert (
            connection.scalar(
                select(func.count()).select_from(reconciled_transaction_sources)
            )
            == 0
        )

    with runtime_engine.begin() as connection:
        _set_context(
            connection,
            installation_id=installation_id,
            residence_id=residence_a,
        )
        assert (
            connection.scalar(
                select(func.count()).select_from(reconciled_transactions)
            )
            == 1
        )
        assert (
            connection.scalar(
                select(func.count()).select_from(reconciled_transaction_sources)
            )
            == 1
        )
