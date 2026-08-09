from __future__ import annotations

from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from meufinanceiro_security.envelope import SecretCipher
from meufinanceiro_security.keyring import create_keyring
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from meufinanceiro_persistence import (
    BankingIntegrationStore,
    ProviderConfigurationState,
    StoredConnectionStatus,
    StoredSyncCycleStatus,
)
from meufinanceiro_persistence.banking_fairness_schema import sync_cycles


@pytest.fixture
def cipher() -> SecretCipher:
    return SecretCipher(create_keyring())


@pytest.fixture
def store(runtime_engine: Engine, cipher: SecretCipher) -> BankingIntegrationStore:
    return BankingIntegrationStore(runtime_engine, cipher)


def test_repeated_empty_snapshots_reuse_completed_noop_cycle(
    engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
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
        external_connection_id="synthetic-empty-fairness",
        status=StoredConnectionStatus.AVAILABLE,
        requires_user_action=False,
    )

    first = store.prepare_sync_cycle(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection.id,
        eligible_external_account_ids=(),
    )
    second = store.prepare_sync_cycle(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection.id,
        eligible_external_account_ids=(),
    )

    assert first.cycle.status is StoredSyncCycleStatus.COMPLETED
    assert second.cycle.id == first.cycle.id
    assert second.accounts == ()
    with engine.begin() as database_connection:
        assert (
            database_connection.scalar(select(func.count()).select_from(sync_cycles))
            == 1
        )
