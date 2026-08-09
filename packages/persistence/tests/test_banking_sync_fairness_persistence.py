from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from meufinanceiro_security.envelope import SecretCipher
from meufinanceiro_security.keyring import create_keyring
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from meufinanceiro_persistence import (
    BankingIntegrationStore,
    ExternalAccountSnapshot,
    ProviderConfigurationState,
    StoredConnectionStatus,
    StoredExternalAccountStatus,
    StoredExternalAccountType,
    StoredSyncCycleStatus,
    SyncConflictError,
)
from meufinanceiro_persistence.banking_fairness_schema import (
    sync_cycle_accounts,
    sync_cycles,
)

NOW = datetime(2026, 8, 9, 18, 0, tzinfo=UTC)


@pytest.fixture
def cipher() -> SecretCipher:
    return SecretCipher(create_keyring())


@pytest.fixture
def store(runtime_engine: Engine, cipher: SecretCipher) -> BankingIntegrationStore:
    return BankingIntegrationStore(runtime_engine, cipher)


def _setup(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
    account_ids: tuple[str, ...],
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
        external_connection_id="synthetic-fairness-connection",
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
            for account_id in account_ids
        ),
    )
    return installation_id, residence_id, connection.id


def _complete_account(
    store: BankingIntegrationStore,
    *,
    installation_id: UUID,
    residence_id: UUID,
    connection_id: UUID,
    cycle_id: UUID,
    account_id: str,
    offset: int,
) -> None:
    store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id=account_id,
        observations=(),
        cursor=None,
        source_window="FULL",
        committed_at=NOW + timedelta(seconds=offset),
        sync_cycle_id=cycle_id,
    )


def test_cycle_progress_survives_runs_and_completed_accounts_stop_competing(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    account_ids = ("fair-account-a", "fair-account-b", "fair-account-c")
    installation_id, residence_id, connection_id = _setup(
        store,
        create_canonical_residences,
        account_ids,
    )

    first = store.prepare_sync_cycle(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        eligible_external_account_ids=account_ids,
    )
    assert first.cycle.status is StoredSyncCycleStatus.OPEN
    assert {item.external_account_id for item in first.pending_accounts} == set(
        account_ids
    )

    _complete_account(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        cycle_id=first.cycle.id,
        account_id="fair-account-a",
        offset=1,
    )

    second = store.prepare_sync_cycle(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        eligible_external_account_ids=account_ids,
    )
    assert second.cycle.id == first.cycle.id
    assert {item.external_account_id for item in second.pending_accounts} == {
        "fair-account-b",
        "fair-account-c",
    }

    _complete_account(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        cycle_id=first.cycle.id,
        account_id="fair-account-b",
        offset=2,
    )
    _complete_account(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        cycle_id=first.cycle.id,
        account_id="fair-account-c",
        offset=3,
    )

    with store._engine.begin() as connection:  # noqa: SLF001 - integration assertion
        status = connection.scalar(
            select(sync_cycles.c.status).where(sync_cycles.c.id == first.cycle.id)
        )
    assert status == StoredSyncCycleStatus.COMPLETED.value

    next_cycle = store.prepare_sync_cycle(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        eligible_external_account_ids=account_ids,
    )
    assert next_cycle.cycle.id != first.cycle.id
    assert next_cycle.cycle.status is StoredSyncCycleStatus.OPEN
    assert len(next_cycle.pending_accounts) == 3


def test_terminal_page_and_cycle_completion_are_atomic(
    engine: Engine,
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id = _setup(
        store,
        create_canonical_residences,
        ("atomic-fair-account",),
    )
    plan = store.prepare_sync_cycle(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        eligible_external_account_ids=("atomic-fair-account",),
    )

    store.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        external_account_id="atomic-fair-account",
        observations=(),
        cursor="opaque-recovery-cursor",
        source_window="FULL",
        committed_at=NOW,
        sync_cycle_id=plan.cycle.id,
    )
    with engine.begin() as connection:
        assert connection.scalar(
            select(sync_cycle_accounts.c.completed_at).where(
                sync_cycle_accounts.c.cycle_id == plan.cycle.id
            )
        ) is None
        assert connection.scalar(
            select(sync_cycles.c.status).where(sync_cycles.c.id == plan.cycle.id)
        ) == StoredSyncCycleStatus.OPEN.value

    _complete_account(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        cycle_id=plan.cycle.id,
        account_id="atomic-fair-account",
        offset=1,
    )
    with engine.begin() as connection:
        assert connection.scalar(
            select(sync_cycle_accounts.c.completed_at).where(
                sync_cycle_accounts.c.cycle_id == plan.cycle.id
            )
        ) is not None
        assert connection.scalar(
            select(sync_cycles.c.status).where(sync_cycles.c.id == plan.cycle.id)
        ) == StoredSyncCycleStatus.COMPLETED.value


def test_snapshot_membership_change_finishes_old_cycle_without_inference(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id = _setup(
        store,
        create_canonical_residences,
        ("present-account", "temporarily-absent-account"),
    )
    plan = store.prepare_sync_cycle(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        eligible_external_account_ids=(
            "present-account",
            "temporarily-absent-account",
        ),
    )
    _complete_account(
        store,
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        cycle_id=plan.cycle.id,
        account_id="present-account",
        offset=1,
    )

    shrunk = store.prepare_sync_cycle(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        eligible_external_account_ids=("present-account",),
    )
    assert shrunk.cycle.id == plan.cycle.id
    assert shrunk.cycle.status is StoredSyncCycleStatus.COMPLETED
    assert tuple(item.external_account_id for item in shrunk.accounts) == (
        "present-account",
    )

    new_cycle = store.prepare_sync_cycle(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        eligible_external_account_ids=("present-account",),
    )
    assert new_cycle.cycle.id != plan.cycle.id
    assert len(new_cycle.pending_accounts) == 1


def test_cycle_scope_rejects_account_from_another_connection(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id = _setup(
        store,
        create_canonical_residences,
        ("owned-account",),
    )

    with pytest.raises(SyncConflictError):
        store.prepare_sync_cycle(
            installation_id=installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
            eligible_external_account_ids=("foreign-account",),
        )


def test_cycle_records_repr_redacts_external_identifiers(
    store: BankingIntegrationStore,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id, residence_id, connection_id = _setup(
        store,
        create_canonical_residences,
        ("sensitive-provider-account-id",),
    )
    plan = store.prepare_sync_cycle(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=connection_id,
        eligible_external_account_ids=("sensitive-provider-account-id",),
    )

    rendered = repr(plan)
    assert "sensitive-provider-account-id" not in rendered
    assert str(plan.cycle.id) not in rendered
    assert "sensitive-provider-account-id" not in repr(plan.accounts[0])
