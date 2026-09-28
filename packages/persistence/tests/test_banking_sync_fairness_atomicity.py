from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from meufinanceiro_security.envelope import SecretCipher
from meufinanceiro_security.keyring import create_keyring
from sqlalchemy import select
from sqlalchemy.engine import Engine

from meufinanceiro_persistence import (
    BankingIntegrationStore,
    BankingPersistenceError,
    ExternalAccountSnapshot,
    ProviderConfigurationState,
    StoredConnectionStatus,
    StoredExternalAccountStatus,
    StoredExternalAccountType,
    StoredSyncCycleStatus,
    StoredTransactionObservationStatus,
    TransactionObservationSnapshot,
)
from meufinanceiro_persistence.banking_fairness_schema import (
    sync_cycle_accounts,
    sync_cycles,
)

NOW = datetime(2026, 8, 9, 19, 0, tzinfo=UTC)


@pytest.fixture
def cipher() -> SecretCipher:
    return SecretCipher(create_keyring())


@pytest.fixture
def store(runtime_engine: Engine, cipher: SecretCipher) -> BankingIntegrationStore:
    return BankingIntegrationStore(runtime_engine, cipher)


def _setup(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> tuple[UUID, UUID, UUID, UUID, str]:
    installation_id = uuid4()
    residence_id = uuid4()
    account_id = "fairness-atomic-account"
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
        external_connection_id="synthetic-fairness-atomic",
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
    plan = store.prepare_sync_cycle(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection.id,
        eligible_external_account_ids=(account_id,),
    )
    return installation_id, residence_id, connection.id, plan.cycle.id, account_id


def test_terminal_failure_rolls_back_cursor_and_fairness_progress_together(
    engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id, cycle_id, account_id = _setup(
        store,
        create_canonical_residences,
    )
    store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=account_id,
        observations=(),
        cursor="recovery-before-terminal",
        source_window="FULL",
        committed_at=NOW,
        sync_cycle_id=cycle_id,
    )

    terminal_at = NOW + timedelta(seconds=1)
    corrupted = TransactionObservationSnapshot(
        external_account_id=account_id,
        external_resource_id="synthetic-corrupted-terminal",
        status=StoredTransactionObservationStatus.CONFIRMED,
        provider_updated_at=terminal_at,
        effective_date=date(2026, 8, 9),
        amount=Decimal("12.34"),
        currency="BRL",
        description="Valid before corruption",
        category="synthetic",
        observed_at=terminal_at,
    )
    object.__setattr__(corrupted, "description", "invalid\ncontrol")

    with pytest.raises(BankingPersistenceError):
        store.apply_transaction_page(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
            external_account_id=account_id,
            observations=(corrupted,),
            cursor=None,
            source_window="FULL",
            committed_at=terminal_at,
            sync_cycle_id=cycle_id,
        )

    cursor = store.get_sync_cursor(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=account_id,
    )
    assert cursor is not None
    assert cursor.cursor == "recovery-before-terminal"

    with engine.begin() as connection:
        progress = (
            connection.execute(
                select(
                    sync_cycle_accounts.c.pages_committed,
                    sync_cycle_accounts.c.completed_at,
                ).where(sync_cycle_accounts.c.cycle_id == cycle_id)
            )
            .mappings()
            .one()
        )
        status = connection.scalar(
            select(sync_cycles.c.status).where(sync_cycles.c.id == cycle_id)
        )

    assert progress["pages_committed"] == 1
    assert progress["completed_at"] is None
    assert status == StoredSyncCycleStatus.OPEN.value
