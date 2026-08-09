from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from meufinanceiro_security.envelope import SecretCipher
from meufinanceiro_security.keyring import create_keyring
from sqlalchemy.engine import Engine

from meufinanceiro_persistence import (
    BankingIntegrationStore,
    ExternalAccountSnapshot,
    ProviderConfigurationState,
    StoredConnectionStatus,
    StoredExternalAccountStatus,
    StoredExternalAccountType,
    StoredSyncCycleStatus,
)

NOW = datetime(2026, 8, 9, 19, 30, tzinfo=UTC)


@pytest.fixture
def cipher() -> SecretCipher:
    return SecretCipher(create_keyring())


@pytest.fixture
def store(runtime_engine: Engine, cipher: SecretCipher) -> BankingIntegrationStore:
    return BankingIntegrationStore(runtime_engine, cipher)


def _setup(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> tuple[UUID, UUID, UUID]:
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
        external_connection_id="synthetic-cycle-reset",
        status=StoredConnectionStatus.AVAILABLE,
        requires_user_action=False,
    )
    store.replace_external_accounts(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection.id,
        snapshots=tuple(
            ExternalAccountSnapshot(
                external_account_id=account_id,
                account_type=StoredExternalAccountType.BANK,
                subtype="CHECKING_ACCOUNT",
                currency="BRL",
                status=StoredExternalAccountStatus.ACTIVE,
                observed_at=NOW,
                number_mask="1234",
            )
            for account_id in ("reset-account-a", "reset-account-b")
        ),
    )
    return installation_id, residence_id, connection.id


def test_first_fairness_cycle_preserves_preexisting_recovery_cursor(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id = _setup(
        store,
        create_canonical_residences,
    )
    store.commit_sync_cursor(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id="reset-account-a",
        cursor="pre-fairness-recovery",
        source_window="FULL",
        committed_at=NOW,
    )

    plan = store.prepare_sync_cycle(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        eligible_external_account_ids=("reset-account-a", "reset-account-b"),
    )

    assert plan.cycle.status is StoredSyncCycleStatus.OPEN
    cursor = store.get_sync_cursor(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id="reset-account-a",
    )
    assert cursor is not None
    assert cursor.cursor == "pre-fairness-recovery"


def test_new_cycle_clears_recovery_cursor_abandoned_by_prior_completed_cycle(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id = _setup(
        store,
        create_canonical_residences,
    )
    first = store.prepare_sync_cycle(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        eligible_external_account_ids=("reset-account-a", "reset-account-b"),
    )

    store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id="reset-account-a",
        observations=(),
        cursor="stale-after-membership-drop",
        source_window="FULL",
        committed_at=NOW,
        sync_cycle_id=first.cycle.id,
    )
    store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id="reset-account-b",
        observations=(),
        cursor=None,
        source_window="FULL",
        committed_at=NOW + timedelta(seconds=1),
        sync_cycle_id=first.cycle.id,
    )

    shrunk = store.prepare_sync_cycle(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        eligible_external_account_ids=("reset-account-b",),
    )
    assert shrunk.cycle.id == first.cycle.id
    assert shrunk.cycle.status is StoredSyncCycleStatus.COMPLETED
    stale_cursor = store.get_sync_cursor(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id="reset-account-a",
    )
    assert stale_cursor is not None
    assert stale_cursor.cursor == "stale-after-membership-drop"

    next_cycle = store.prepare_sync_cycle(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        eligible_external_account_ids=("reset-account-a", "reset-account-b"),
    )
    assert next_cycle.cycle.id != first.cycle.id
    assert next_cycle.cycle.status is StoredSyncCycleStatus.OPEN
    assert {account.external_account_id for account in next_cycle.pending_accounts} == {
        "reset-account-a",
        "reset-account-b",
    }
    assert all(account.pages_committed == 0 for account in next_cycle.pending_accounts)
    assert (
        store.get_sync_cursor(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
            external_account_id="reset-account-a",
        )
        is None
    )
