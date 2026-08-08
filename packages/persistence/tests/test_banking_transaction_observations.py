from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from meufinanceiro_security.envelope import SecretCipher
from meufinanceiro_security.keyring import create_keyring
from sqlalchemy import func, select
from sqlalchemy.engine import Connection, Engine

from meufinanceiro_persistence.banking import (
    BankingIntegrationStore,
    BankingPersistenceError,
    ExternalAccountNotFoundError,
    ExternalAccountSnapshot,
    ProviderConfigurationState,
    StoredConnectionStatus,
    StoredExternalAccountStatus,
    StoredExternalAccountType,
    StoredTransactionObservationStatus,
    SyncConflictError,
    TransactionObservationSnapshot,
)
from meufinanceiro_persistence.banking_observation_schema import external_observations
from meufinanceiro_persistence.schema import sync_cursors

NOW = datetime(2026, 8, 8, 4, 30, tzinfo=UTC)


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


def _setup_connection_and_account(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
    *,
    installation_id: UUID,
    residence_id: UUID,
    external_connection_id: str,
    external_account_id: str,
) -> UUID:
    create_canonical_residences(installation_id, (residence_id,))
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
                external_account_id=external_account_id,
                account_type=StoredExternalAccountType.BANK,
                subtype="CHECKING_ACCOUNT",
                currency="BRL",
                status=StoredExternalAccountStatus.ACTIVE,
                observed_at=NOW,
                name="Conta sintética",
                number_mask="1234",
            ),
        ),
    )
    return connection.id


def _observation(
    external_account_id: str,
    *,
    external_resource_id: str | None = "synthetic-transaction-001",
    status: StoredTransactionObservationStatus = (
        StoredTransactionObservationStatus.PENDING
    ),
    amount: Decimal = Decimal("25.50"),
    observed_at: datetime = NOW,
    description: str | None = "Compra sintética",
) -> TransactionObservationSnapshot:
    return TransactionObservationSnapshot(
        external_account_id=external_account_id,
        external_resource_id=external_resource_id,
        status=status,
        provider_updated_at=observed_at,
        effective_date=date(2026, 8, 8),
        amount=amount,
        currency="BRL",
        description=description,
        category="synthetic-category",
        observed_at=observed_at,
    )


def test_page_and_cursor_commit_atomically_and_repeat_idempotently(
    engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    account_id = "synthetic-account-atomic"
    connection_id = _setup_connection_and_account(
        store,
        create_canonical_residences,
        installation_id=installation_id,
        residence_id=residence_id,
        external_connection_id="synthetic-item-atomic",
        external_account_id=account_id,
    )
    observation = _observation(account_id)

    result = store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=account_id,
        observations=(observation,),
        cursor="opaque-cursor-page-001",
        source_window="2026-08-01..2026-08-08",
        committed_at=NOW,
    )
    assert result.records_seen == 1
    assert result.records_applied == 1
    assert result.committed_at == NOW

    repeated = store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=account_id,
        observations=(observation,),
        cursor="opaque-cursor-page-001",
        source_window="2026-08-01..2026-08-08",
        committed_at=NOW,
    )
    assert repeated.records_seen == 1
    assert repeated.records_applied == 0

    with engine.begin() as connection:
        assert (
            connection.scalar(
                select(func.count()).select_from(external_observations)
            )
            == 1
        )
        assert connection.scalar(select(func.count()).select_from(sync_cursors)) == 1


def test_committed_cursor_replay_cannot_append_different_page(
    engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    account_id = "synthetic-account-replay"
    connection_id = _setup_connection_and_account(
        store,
        create_canonical_residences,
        installation_id=installation_id,
        residence_id=residence_id,
        external_connection_id="synthetic-item-replay",
        external_account_id=account_id,
    )
    first = _observation(account_id, external_resource_id="synthetic-tx-replay-1")
    different = _observation(
        account_id,
        external_resource_id="synthetic-tx-replay-2",
    )

    store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=account_id,
        observations=(first,),
        cursor="cursor-replay",
        source_window="window-replay",
        committed_at=NOW,
    )
    replay = store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=account_id,
        observations=(different,),
        cursor="cursor-replay",
        source_window="window-replay",
        committed_at=NOW,
    )
    assert replay.records_applied == 0

    with engine.begin() as connection:
        rows = connection.execute(
            select(external_observations.c.external_resource_id)
        ).scalars().all()
    assert rows == ["synthetic-tx-replay-1"]


def test_same_provider_identity_updates_status_without_duplication(
    engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    account_id = "synthetic-account-status"
    connection_id = _setup_connection_and_account(
        store,
        create_canonical_residences,
        installation_id=installation_id,
        residence_id=residence_id,
        external_connection_id="synthetic-item-status",
        external_account_id=account_id,
    )
    pending = _observation(account_id)
    confirmed = _observation(
        account_id,
        status=StoredTransactionObservationStatus.CONFIRMED,
        amount=Decimal("26.00"),
        observed_at=NOW + timedelta(minutes=1),
        description="Descrição confirmada",
    )
    assert pending.stable_fingerprint == confirmed.stable_fingerprint

    store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=account_id,
        observations=(pending,),
        cursor="cursor-status-001",
        source_window="window-001",
        committed_at=NOW,
    )
    store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=account_id,
        observations=(confirmed,),
        cursor="cursor-status-002",
        source_window="window-002",
        committed_at=NOW + timedelta(minutes=1),
    )

    with engine.begin() as connection:
        rows = connection.execute(
            select(
                external_observations.c.status,
                external_observations.c.amount,
                external_observations.c.description,
            )
        ).mappings().all()
    assert len(rows) == 1
    assert rows[0]["status"] == "CONFIRMED"
    assert rows[0]["amount"] == Decimal("26.00000000")
    assert rows[0]["description"] == "Descrição confirmada"


def test_stale_observation_does_not_regress_newer_metadata(
    engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    account_id = "synthetic-account-stale"
    connection_id = _setup_connection_and_account(
        store,
        create_canonical_residences,
        installation_id=installation_id,
        residence_id=residence_id,
        external_connection_id="synthetic-item-stale",
        external_account_id=account_id,
    )
    newer = _observation(
        account_id,
        status=StoredTransactionObservationStatus.CONFIRMED,
        observed_at=NOW + timedelta(minutes=2),
        description="Novo",
    )
    older = _observation(
        account_id,
        status=StoredTransactionObservationStatus.PENDING,
        observed_at=NOW + timedelta(minutes=1),
        description="Antigo",
    )

    store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=account_id,
        observations=(newer,),
        cursor="cursor-stale-001",
        source_window="window-stale-001",
        committed_at=NOW + timedelta(minutes=2),
    )
    store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=account_id,
        observations=(older,),
        cursor="cursor-stale-002",
        source_window="window-stale-002",
        committed_at=NOW + timedelta(minutes=3),
    )

    with engine.begin() as connection:
        row = connection.execute(
            select(
                external_observations.c.status,
                external_observations.c.description,
                external_observations.c.last_seen_at,
            )
        ).mappings().one()
    assert row["status"] == "CONFIRMED"
    assert row["description"] == "Novo"
    assert row["last_seen_at"] == NOW + timedelta(minutes=2)


def test_page_rejects_wrong_account_and_future_observation_before_commit(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    account_id = "synthetic-account-validation"
    connection_id = _setup_connection_and_account(
        store,
        create_canonical_residences,
        installation_id=installation_id,
        residence_id=residence_id,
        external_connection_id="synthetic-item-validation",
        external_account_id=account_id,
    )

    with pytest.raises(ValueError, match="another account"):
        store.apply_transaction_page(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
            external_account_id=account_id,
            observations=(_observation("other-account"),),
            cursor="cursor-wrong-account",
            source_window="window-wrong-account",
            committed_at=NOW,
        )

    with pytest.raises(ValueError, match="newer than the page commit"):
        store.apply_transaction_page(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
            external_account_id=account_id,
            observations=(
                _observation(
                    account_id,
                    observed_at=NOW + timedelta(seconds=1),
                ),
            ),
            cursor="cursor-future-observation",
            source_window="window-future-observation",
            committed_at=NOW,
        )


def test_cross_connection_account_is_rejected_under_scoped_lock(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    first_account_id = "synthetic-account-scope-a"
    first_connection_id = _setup_connection_and_account(
        store,
        create_canonical_residences,
        installation_id=installation_id,
        residence_id=residence_id,
        external_connection_id="synthetic-item-scope-a",
        external_account_id=first_account_id,
    )
    second_connection = store.register_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        provider="pluggy",
        external_connection_id="synthetic-item-scope-b",
        status=StoredConnectionStatus.AVAILABLE,
        requires_user_action=False,
    )
    second_account_id = "synthetic-account-scope-b"
    store.replace_external_accounts(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=second_connection.id,
        snapshots=(
            ExternalAccountSnapshot(
                external_account_id=second_account_id,
                account_type=StoredExternalAccountType.BANK,
                subtype="CHECKING_ACCOUNT",
                currency="BRL",
                status=StoredExternalAccountStatus.ACTIVE,
                observed_at=NOW,
                number_mask="4321",
            ),
        ),
    )

    with pytest.raises(ExternalAccountNotFoundError):
        store.apply_transaction_page(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=first_connection_id,
            external_account_id=second_account_id,
            observations=(_observation(second_account_id),),
            cursor="cursor-cross-connection",
            source_window="window-cross-connection",
            committed_at=NOW,
        )


def test_empty_page_can_advance_cursor_explicitly(
    engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    account_id = "synthetic-account-empty"
    connection_id = _setup_connection_and_account(
        store,
        create_canonical_residences,
        installation_id=installation_id,
        residence_id=residence_id,
        external_connection_id="synthetic-item-empty",
        external_account_id=account_id,
    )

    result = store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=account_id,
        observations=(),
        cursor="cursor-empty",
        source_window="window-empty",
        committed_at=NOW,
    )
    assert result.records_seen == 0
    assert result.records_applied == 0

    with engine.begin() as connection:
        assert (
            connection.scalar(
                select(func.count()).select_from(external_observations)
            )
            == 0
        )
        assert connection.scalar(select(func.count()).select_from(sync_cursors)) == 1


def test_failure_inside_page_rolls_back_prior_observations_and_cursor(
    engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    account_id = "synthetic-account-rollback"
    connection_id = _setup_connection_and_account(
        store,
        create_canonical_residences,
        installation_id=installation_id,
        residence_id=residence_id,
        external_connection_id="synthetic-item-rollback",
        external_account_id=account_id,
    )
    store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=account_id,
        observations=(),
        cursor="cursor-before-failure",
        source_window="window-before-failure",
        committed_at=NOW,
    )

    valid = _observation(
        account_id,
        external_resource_id="synthetic-valid-before-failure",
        observed_at=NOW + timedelta(minutes=1),
    )
    corrupted = _observation(
        account_id,
        external_resource_id="synthetic-invalid-after-valid",
        observed_at=NOW + timedelta(minutes=1),
    )
    object.__setattr__(corrupted, "description", "invalid\ncontrol")

    with pytest.raises(
        BankingPersistenceError,
        match="transaction observation page could not be persisted",
    ):
        store.apply_transaction_page(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
            external_account_id=account_id,
            observations=(valid, corrupted),
            cursor="cursor-after-failure",
            source_window="window-after-failure",
            committed_at=NOW + timedelta(minutes=1),
        )

    with engine.begin() as connection:
        assert (
            connection.scalar(
                select(func.count()).select_from(external_observations)
            )
            == 0
        )
    cursor = store.get_sync_cursor(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=account_id,
    )
    assert cursor is not None
    assert cursor.cursor == "cursor-before-failure"


def test_duplicate_page_identity_and_stale_cursor_fail_closed(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    account_id = "synthetic-account-conflict"
    connection_id = _setup_connection_and_account(
        store,
        create_canonical_residences,
        installation_id=installation_id,
        residence_id=residence_id,
        external_connection_id="synthetic-item-conflict",
        external_account_id=account_id,
    )
    observation = _observation(account_id)

    with pytest.raises(ValueError, match="duplicate observations"):
        store.apply_transaction_page(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
            external_account_id=account_id,
            observations=(observation, observation),
            cursor="cursor-duplicate",
            source_window="window-duplicate",
            committed_at=NOW,
        )

    store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=account_id,
        observations=(observation,),
        cursor="cursor-current",
        source_window="window-current",
        committed_at=NOW + timedelta(minutes=2),
    )
    with pytest.raises(SyncConflictError, match="stale"):
        store.apply_transaction_page(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
            external_account_id=account_id,
            observations=(),
            cursor="cursor-stale",
            source_window="window-stale",
            committed_at=NOW + timedelta(minutes=1),
        )


def test_observation_rls_is_fail_closed_and_residence_scoped(
    runtime_engine: Engine,
    engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_a = uuid4()
    residence_b = uuid4()
    create_canonical_residences(installation_id, (residence_a, residence_b))
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
    connection = store.register_connection(
        installation_id=installation_id,
        residence_id=residence_a,
        provider="pluggy",
        external_connection_id="synthetic-item-rls-observation",
        status=StoredConnectionStatus.AVAILABLE,
        requires_user_action=False,
    )
    account_id = "synthetic-account-rls-observation"
    store.replace_external_accounts(
        installation_id=installation_id,
        residence_id=residence_a,
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
    store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_a,
        connection_id=connection.id,
        external_account_id=account_id,
        observations=(_observation(account_id),),
        cursor="cursor-rls-observation",
        source_window="window-rls-observation",
        committed_at=NOW,
    )

    with runtime_engine.begin() as connection_runtime:
        assert (
            connection_runtime.scalar(
                select(func.count()).select_from(external_observations)
            )
            == 0
        )

    with runtime_engine.begin() as connection_runtime:
        _set_context(
            connection_runtime,
            installation_id=installation_id,
            residence_id=residence_b,
        )
        assert (
            connection_runtime.scalar(
                select(func.count()).select_from(external_observations)
            )
            == 0
        )

    with runtime_engine.begin() as connection_runtime:
        _set_context(
            connection_runtime,
            installation_id=installation_id,
            residence_id=residence_a,
        )
        assert (
            connection_runtime.scalar(
                select(func.count()).select_from(external_observations)
            )
            == 1
        )

    with engine.begin() as admin_connection:
        row = admin_connection.execute(
            select(
                external_observations.c.status,
                external_observations.c.normalized_payload_version,
            )
        ).mappings().one()
    assert row["status"] == "PENDING"
    assert row["normalized_payload_version"] == 1
