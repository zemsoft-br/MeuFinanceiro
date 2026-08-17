from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    FinancialAccountDraft,
    FinancialAccountType,
    FinancialMovementDraft,
    FinancialResultEffect,
    FinancialVisibilityScope,
    Money,
    new_financial_idempotency_key,
)
from meufinanceiro_security.envelope import SecretCipher
from meufinanceiro_security.keyring import create_keyring
from sqlalchemy import Table, func, insert, select, update
from sqlalchemy.engine import Engine

from meufinanceiro_persistence import (
    BankingIntegrationStore,
    BankingLedgerReviewConflictError,
    BankingLedgerReviewDecision,
    BankingLedgerReviewDraft,
    BankingLedgerReviewNotEligibleError,
    BankingLedgerReviewRecord,
    BankingLedgerReviewStore,
    ExternalAccountSnapshot,
    ProviderConfigurationState,
    StoredConnectionStatus,
    StoredExternalAccountStatus,
    StoredExternalAccountType,
    StoredTransactionObservationStatus,
    TransactionObservationSnapshot,
)
from meufinanceiro_persistence.banking_ledger_review_schema import (
    reconciled_transaction_ledger_links,
)
from meufinanceiro_persistence.banking_observation_schema import external_observations
from meufinanceiro_persistence.banking_reconciliation_schema import (
    reconciled_transactions,
)
from meufinanceiro_persistence.financial_account_store import FinancialAccountStore
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import FinancialMovementStore
from meufinanceiro_persistence.schema import (
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
)

NOW = datetime(2026, 8, 16, 4, 30, tzinfo=UTC)


def _create_household(engine: Engine) -> tuple[UUID, UUID, UUID, UUID]:
    installation_id = uuid4()
    residence_id = uuid4()
    owner_id = uuid4()
    member_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            insert(identity_installation).values(
                singleton=True,
                id=installation_id,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            insert(household_residences).values(
                id=residence_id,
                installation_id=installation_id,
                name="Synthetic ledger review household",
                status="active",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        for index, (operator_id, role) in enumerate(
            ((owner_id, "owner"), (member_id, "member"))
        ):
            connection.execute(
                insert(identity_operators).values(
                    id=operator_id,
                    installation_id=installation_id,
                    login_name=f"ledger-review-{index}",
                    password_hash="synthetic-password-hash-material-000000000000",
                    role="installation_admin",
                    status="active",
                    failed_attempts=0,
                    locked_until=None,
                    last_authenticated_at=None,
                    password_changed_at=NOW,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            connection.execute(
                insert(household_memberships).values(
                    id=uuid4(),
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    role=role,
                    status="active",
                    is_primary=index == 0,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
    return installation_id, residence_id, owner_id, member_id


def _create_financial_account(
    runtime_engine: Engine,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
) -> UUID:
    account = FinancialAccountStore(runtime_engine).create_account(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
        draft=FinancialAccountDraft(
            name="Synthetic reviewed account",
            currency="BRL",
            account_type=FinancialAccountType.CHECKING,
            visibility_scope=FinancialVisibilityScope.PERSONAL,
        ),
    )
    return account.id


def _create_reconciled_transaction(
    engine: Engine,
    runtime_engine: Engine,
    *,
    installation_id: UUID,
    residence_id: UUID,
    amount: str,
    status: StoredTransactionObservationStatus = (
        StoredTransactionObservationStatus.CONFIRMED
    ),
    description: str | None = "Synthetic reviewed transaction",
) -> UUID:
    banking = BankingIntegrationStore(
        runtime_engine,
        SecretCipher(create_keyring()),
    )
    configured = banking.create_configuration(
        installation_id=installation_id,
        provider="pluggy",
        client_id="synthetic-client-id",
        client_secret="synthetic-client-secret",
    )
    banking.set_configuration_state(
        installation_id=installation_id,
        provider="pluggy",
        expected_revision=configured.configuration_revision,
        state=ProviderConfigurationState.ENABLED,
    )
    external_account_id = f"synthetic-account-{uuid4()}"
    external_connection_id = f"synthetic-connection-{uuid4()}"
    stored_connection = banking.register_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        provider="pluggy",
        external_connection_id=external_connection_id,
        status=StoredConnectionStatus.AVAILABLE,
        requires_user_action=False,
    )
    banking.replace_external_accounts(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=stored_connection.id,
        snapshots=(
            ExternalAccountSnapshot(
                external_account_id=external_account_id,
                account_type=StoredExternalAccountType.BANK,
                subtype="CHECKING_ACCOUNT",
                currency="BRL",
                status=StoredExternalAccountStatus.ACTIVE,
                observed_at=NOW,
                number_mask="1234",
            ),
        ),
    )
    banking.apply_transaction_page(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=stored_connection.id,
        external_account_id=external_account_id,
        observations=(
            TransactionObservationSnapshot(
                external_account_id=external_account_id,
                external_resource_id=f"transaction-{uuid4()}",
                status=status,
                provider_updated_at=NOW,
                effective_date=date(2026, 8, 15),
                amount=Decimal(amount),
                currency="BRL",
                description=description,
                category="synthetic",
                observed_at=NOW,
            ),
        ),
        cursor=None,
        source_window="FULL",
        committed_at=NOW,
    )
    banking.reconcile_transaction_observations(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=stored_connection.id,
    )
    with engine.begin() as connection:
        reconciled_id = connection.scalar(
            select(reconciled_transactions.c.id).where(
                reconciled_transactions.c.connection_id == stored_connection.id,
                reconciled_transactions.c.residence_id == residence_id,
            )
        )
    assert isinstance(reconciled_id, UUID)
    return reconciled_id


def _count(engine: Engine, table: Table) -> int:
    with engine.begin() as connection:
        value = connection.scalar(select(func.count()).select_from(table))
    assert isinstance(value, int)
    return value


def test_confirmed_income_import_is_atomic_and_idempotent(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    account_id = _create_financial_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
    )
    reconciled_id = _create_reconciled_transaction(
        engine,
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        amount="150.25",
    )
    store = BankingLedgerReviewStore(runtime_engine)
    candidate = store.get_candidate(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        reconciled_transaction_id=reconciled_id,
    )
    assert candidate.amount == Decimal("150.25000000")
    assert candidate.status is StoredTransactionObservationStatus.CONFIRMED

    key = new_financial_idempotency_key()
    draft = BankingLedgerReviewDraft(
        source_observation_id=candidate.source_observation_id,
        source_observation_updated_at=candidate.source_observation_updated_at,
        decision=BankingLedgerReviewDecision.IMPORT_AS_INCOME,
        financial_account_id=account_id,
    )
    created = store.decide(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        reconciled_transaction_id=reconciled_id,
        idempotency_key=key,
        draft=draft,
    )
    replay = store.decide(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        reconciled_transaction_id=reconciled_id,
        idempotency_key=key,
        draft=draft,
    )

    assert replay == created
    assert created.decision is BankingLedgerReviewDecision.IMPORT_AS_INCOME
    assert created.financial_account_id == account_id
    assert created.movement_id is not None
    assert _count(engine, reconciled_transaction_ledger_links) == 1
    assert _count(engine, financial_movements) == 1

    with engine.begin() as connection:
        movement = (
            connection.execute(
                select(financial_movements).where(
                    financial_movements.c.id == created.movement_id
                )
            )
            .mappings()
            .one()
        )
    assert movement["amount"] == Decimal("150.25000000")
    assert movement["result_effect"] == "INCOME"
    assert movement["role"] == "STANDARD"
    assert movement["effective_date"] == date(2026, 8, 15)
    assert movement["competence_date"] == date(2026, 8, 15)
    assert movement["idempotency_key"] != key

    with pytest.raises(BankingLedgerReviewConflictError):
        store.decide(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            reconciled_transaction_id=reconciled_id,
            idempotency_key=key,
            draft=BankingLedgerReviewDraft(
                source_observation_id=candidate.source_observation_id,
                source_observation_updated_at=candidate.source_observation_updated_at,
                decision=BankingLedgerReviewDecision.IGNORE,
            ),
        )


def test_stale_source_snapshot_fails_before_creating_movement(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    account_id = _create_financial_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
    )
    reconciled_id = _create_reconciled_transaction(
        engine,
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        amount="75.00",
    )
    store = BankingLedgerReviewStore(runtime_engine)
    candidate = store.get_candidate(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        reconciled_transaction_id=reconciled_id,
    )
    with engine.begin() as connection:
        connection.execute(
            update(external_observations)
            .where(external_observations.c.id == candidate.source_observation_id)
            .values(updated_at=NOW + timedelta(minutes=1))
        )

    with pytest.raises(BankingLedgerReviewConflictError):
        store.decide(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            reconciled_transaction_id=reconciled_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=BankingLedgerReviewDraft(
                source_observation_id=candidate.source_observation_id,
                source_observation_updated_at=candidate.source_observation_updated_at,
                decision=BankingLedgerReviewDecision.IMPORT_AS_INCOME,
                financial_account_id=account_id,
            ),
        )

    assert _count(engine, reconciled_transaction_ledger_links) == 0
    assert _count(engine, financial_movements) == 0


def test_link_existing_is_explicit_and_does_not_copy_movement(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    account_id = _create_financial_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
    )
    reconciled_id = _create_reconciled_transaction(
        engine,
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        amount="42.00",
    )
    movement = FinancialMovementStore(runtime_engine).create_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementDraft(
            account_id=account_id,
            amount=Money(Decimal("42.00"), "BRL"),
            result_effect=FinancialResultEffect.INCOME,
            effective_date=date(2026, 8, 15),
            competence_date=date(2026, 8, 15),
            description="Existing synthetic Movement",
        ),
    )
    store = BankingLedgerReviewStore(runtime_engine)
    candidate = store.get_candidate(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        reconciled_transaction_id=reconciled_id,
    )
    linked = store.decide(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        reconciled_transaction_id=reconciled_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=BankingLedgerReviewDraft(
            source_observation_id=candidate.source_observation_id,
            source_observation_updated_at=candidate.source_observation_updated_at,
            decision=BankingLedgerReviewDecision.LINK_EXISTING_MOVEMENT,
            movement_id=movement.id,
        ),
    )

    assert linked.movement_id == movement.id
    assert linked.financial_account_id == account_id
    assert _count(engine, reconciled_transaction_ledger_links) == 1
    assert _count(engine, financial_movements) == 1


def test_pending_can_be_ignored_but_not_imported(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    account_id = _create_financial_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
    )
    reconciled_id = _create_reconciled_transaction(
        engine,
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        amount="20.00",
        status=StoredTransactionObservationStatus.PENDING,
    )
    store = BankingLedgerReviewStore(runtime_engine)
    candidate = store.get_candidate(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        reconciled_transaction_id=reconciled_id,
    )
    assert candidate.status is StoredTransactionObservationStatus.PENDING

    with pytest.raises(BankingLedgerReviewNotEligibleError):
        store.decide(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            reconciled_transaction_id=reconciled_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=BankingLedgerReviewDraft(
                source_observation_id=candidate.source_observation_id,
                source_observation_updated_at=candidate.source_observation_updated_at,
                decision=BankingLedgerReviewDecision.IMPORT_AS_INCOME,
                financial_account_id=account_id,
            ),
        )
    assert _count(engine, reconciled_transaction_ledger_links) == 0
    assert _count(engine, financial_movements) == 0

    ignored = store.decide(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        reconciled_transaction_id=reconciled_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=BankingLedgerReviewDraft(
            source_observation_id=candidate.source_observation_id,
            source_observation_updated_at=candidate.source_observation_updated_at,
            decision=BankingLedgerReviewDecision.IGNORE,
        ),
    )
    assert ignored.movement_id is None
    assert _count(engine, reconciled_transaction_ledger_links) == 1
    assert _count(engine, financial_movements) == 0


def test_concurrent_imports_create_exactly_one_movement(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, _member_id = _create_household(engine)
    account_id = _create_financial_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
    )
    reconciled_id = _create_reconciled_transaction(
        engine,
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        amount="99.00",
    )
    store = BankingLedgerReviewStore(runtime_engine)
    candidate = store.get_candidate(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        reconciled_transaction_id=reconciled_id,
    )
    draft = BankingLedgerReviewDraft(
        source_observation_id=candidate.source_observation_id,
        source_observation_updated_at=candidate.source_observation_updated_at,
        decision=BankingLedgerReviewDecision.IMPORT_AS_INCOME,
        financial_account_id=account_id,
    )
    barrier = Barrier(2)

    def _worker(key: UUID) -> BankingLedgerReviewRecord | None:
        barrier.wait()
        try:
            return store.decide(
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=owner_id,
                reconciled_transaction_id=reconciled_id,
                idempotency_key=key,
                draft=draft,
            )
        except BankingLedgerReviewConflictError:
            return None

    keys = (new_financial_idempotency_key(), new_financial_idempotency_key())
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(_worker, keys))

    assert sum(result is not None for result in results) == 1
    assert _count(engine, reconciled_transaction_ledger_links) == 1
    assert _count(engine, financial_movements) == 1


def test_link_conflict_after_provisional_movement_rolls_back_atomically(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, member_id = _create_household(engine)
    member_account_id = _create_financial_account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=member_id,
    )
    reconciled_id = _create_reconciled_transaction(
        engine,
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        amount="33.00",
    )
    store = BankingLedgerReviewStore(runtime_engine)
    owner_candidate = store.get_candidate(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        reconciled_transaction_id=reconciled_id,
    )
    store.decide(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        reconciled_transaction_id=reconciled_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=BankingLedgerReviewDraft(
            source_observation_id=owner_candidate.source_observation_id,
            source_observation_updated_at=(
                owner_candidate.source_observation_updated_at
            ),
            decision=BankingLedgerReviewDecision.IGNORE,
        ),
    )

    member_candidate = store.get_candidate(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=member_id,
        reconciled_transaction_id=reconciled_id,
    )
    with pytest.raises(BankingLedgerReviewConflictError):
        store.decide(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=member_id,
            reconciled_transaction_id=reconciled_id,
            idempotency_key=new_financial_idempotency_key(),
            draft=BankingLedgerReviewDraft(
                source_observation_id=member_candidate.source_observation_id,
                source_observation_updated_at=(
                    member_candidate.source_observation_updated_at
                ),
                decision=BankingLedgerReviewDecision.IMPORT_AS_INCOME,
                financial_account_id=member_account_id,
            ),
        )

    assert _count(engine, reconciled_transaction_ledger_links) == 1
    assert _count(engine, financial_movements) == 0
