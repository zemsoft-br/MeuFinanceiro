from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from meufinanceiro_security.envelope import SecretCipher
from meufinanceiro_security.keyring import create_keyring
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from meufinanceiro_persistence.banking import (
    BankingIntegrationStore,
    BankingPersistenceError,
    ExternalAccountSnapshot,
    ProviderConfigurationState,
    StoredConnectionStatus,
    StoredExternalAccountStatus,
    StoredExternalAccountType,
    StoredTransactionObservationStatus,
    TransactionObservationSnapshot,
)
from meufinanceiro_persistence.banking_observation_schema import external_observations
from meufinanceiro_persistence.schema import sync_cursors

NOW = datetime(2026, 8, 9, 4, 30, tzinfo=UTC)


@pytest.fixture
def cipher() -> SecretCipher:
    return SecretCipher(create_keyring())


@pytest.fixture
def store(runtime_engine: Engine, cipher: SecretCipher) -> BankingIntegrationStore:
    return BankingIntegrationStore(runtime_engine, cipher)


def _setup(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> tuple[UUID, UUID, UUID, str]:
    installation_id = uuid4()
    residence_id = uuid4()
    account_id = "synthetic-terminal-account"
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
        external_connection_id="synthetic-terminal-connection",
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
    return installation_id, residence_id, connection.id, account_id


def _observation(
    account_id: str,
    *,
    identifier: str,
    observed_at: datetime,
) -> TransactionObservationSnapshot:
    return TransactionObservationSnapshot(
        external_account_id=account_id,
        external_resource_id=identifier,
        status=StoredTransactionObservationStatus.CONFIRMED,
        provider_updated_at=observed_at,
        effective_date=date(2026, 8, 9),
        amount=Decimal("12.34"),
        currency="BRL",
        description="Transação sintética",
        category="synthetic",
        observed_at=observed_at,
    )


def test_terminal_page_removes_recovery_cursor_in_same_commit(
    engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id, account_id = _setup(
        store,
        create_canonical_residences,
    )
    first = _observation(account_id, identifier="synthetic-page-1", observed_at=NOW)
    store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=account_id,
        observations=(first,),
        cursor="recovery-cursor-001",
        source_window="FULL",
        committed_at=NOW,
    )

    terminal_at = NOW + timedelta(seconds=1)
    terminal = _observation(
        account_id,
        identifier="synthetic-page-terminal",
        observed_at=terminal_at,
    )
    result = store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=account_id,
        observations=(terminal,),
        cursor=None,
        source_window="FULL",
        committed_at=terminal_at,
    )

    assert result.records_seen == 1
    assert result.records_applied == 1
    assert (
        store.get_sync_cursor(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
            external_account_id=account_id,
        )
        is None
    )
    with engine.begin() as connection:
        assert connection.scalar(select(func.count()).select_from(sync_cursors)) == 0
        assert (
            connection.scalar(select(func.count()).select_from(external_observations))
            == 2
        )


def test_terminal_page_failure_rolls_back_and_preserves_previous_cursor(
    engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id, account_id = _setup(
        store,
        create_canonical_residences,
    )
    store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=account_id,
        observations=(),
        cursor="recovery-cursor-before-failure",
        source_window="FULL",
        committed_at=NOW,
    )

    terminal_at = NOW + timedelta(seconds=1)
    corrupted = _observation(
        account_id,
        identifier="synthetic-invalid-terminal",
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
        )

    cursor = store.get_sync_cursor(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=account_id,
    )
    assert cursor is not None
    assert cursor.cursor == "recovery-cursor-before-failure"
    with engine.begin() as connection:
        assert connection.scalar(select(func.count()).select_from(sync_cursors)) == 1
        assert (
            connection.scalar(select(func.count()).select_from(external_observations))
            == 0
        )


def test_terminal_page_without_previous_cursor_is_valid(
    engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id, account_id = _setup(
        store,
        create_canonical_residences,
    )
    terminal = _observation(
        account_id,
        identifier="synthetic-single-terminal",
        observed_at=NOW,
    )

    result = store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=account_id,
        observations=(terminal,),
        cursor=None,
        source_window="FULL",
        committed_at=NOW,
    )

    assert result.records_applied == 1
    with engine.begin() as connection:
        assert connection.scalar(select(func.count()).select_from(sync_cursors)) == 0
        assert (
            connection.scalar(select(func.count()).select_from(external_observations))
            == 1
        )
