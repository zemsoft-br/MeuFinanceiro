from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal
from threading import Barrier
from uuid import UUID, uuid4

from meufinanceiro_finance import (
    FinancialAccountDraft,
    FinancialAccountType,
    FinancialVisibilityScope,
    new_financial_idempotency_key,
)
from meufinanceiro_security.envelope import SecretCipher
from meufinanceiro_security.keyring import create_keyring
from sqlalchemy import insert, select
from sqlalchemy.engine import Engine

from meufinanceiro_persistence import (
    BankingIntegrationStore,
    BankingLedgerReviewDecision,
    BankingLedgerReviewDraft,
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
from meufinanceiro_persistence.banking_reconciliation_schema import (
    reconciled_transactions,
)
from meufinanceiro_persistence.financial_account_store import FinancialAccountStore
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.schema import (
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
)

_NOW = datetime(2026, 8, 16, 5, 0, tzinfo=UTC)


def _household(engine: Engine) -> tuple[UUID, UUID, UUID]:
    installation_id = uuid4()
    residence_id = uuid4()
    operator_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            insert(identity_installation).values(
                singleton=True,
                id=installation_id,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        connection.execute(
            insert(identity_operators).values(
                id=operator_id,
                installation_id=installation_id,
                login_name="ledger-review-regression-owner",
                password_hash="synthetic-password-hash-material-000000000000",
                role="installation_admin",
                status="active",
                failed_attempts=0,
                locked_until=None,
                last_authenticated_at=None,
                password_changed_at=_NOW,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        connection.execute(
            insert(household_residences).values(
                id=residence_id,
                installation_id=installation_id,
                name="Synthetic ledger review regression residence",
                status="active",
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        connection.execute(
            insert(household_memberships).values(
                id=uuid4(),
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=operator_id,
                role="owner",
                status="active",
                is_primary=True,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
    return installation_id, residence_id, operator_id


def _account(
    runtime_engine: Engine,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
) -> UUID:
    return FinancialAccountStore(runtime_engine).create_account(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
        draft=FinancialAccountDraft(
            name="Synthetic regression account",
            currency="BRL",
            account_type=FinancialAccountType.CHECKING,
            visibility_scope=FinancialVisibilityScope.PERSONAL,
        ),
    ).id


def _reconciled(
    engine: Engine,
    runtime_engine: Engine,
    *,
    installation_id: UUID,
    residence_id: UUID,
    amount: Decimal,
) -> UUID:
    banking = BankingIntegrationStore(
        runtime_engine,
        SecretCipher(create_keyring()),
    )
    provider = f"synthetic_{uuid4().hex[:12]}"
    configured = banking.create_configuration(
        installation_id=installation_id,
        provider=provider,
        client_id="synthetic-client-id",
        client_secret="synthetic-client-secret",
    )
    banking.set_configuration_state(
        installation_id=installation_id,
        provider=provider,
        expected_revision=configured.configuration_revision,
        state=ProviderConfigurationState.ENABLED,
    )
    external_account_id = f"synthetic-account-{uuid4()}"
    stored_connection = banking.register_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        provider=provider,
        external_connection_id=f"synthetic-connection-{uuid4()}",
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
                observed_at=_NOW,
                number_mask="9876",
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
                external_resource_id=f"synthetic-transaction-{uuid4()}",
                status=StoredTransactionObservationStatus.CONFIRMED,
                provider_updated_at=_NOW,
                effective_date=date(2026, 8, 15),
                amount=amount,
                currency="BRL",
                description="Synthetic regression transaction",
                category="synthetic",
                observed_at=_NOW,
            ),
        ),
        cursor=None,
        source_window="FULL",
        committed_at=_NOW,
    )
    banking.reconcile_transaction_observations(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=stored_connection.id,
    )
    with engine.begin() as connection:
        value = connection.scalar(
            select(reconciled_transactions.c.id).where(
                reconciled_transactions.c.connection_id == stored_connection.id,
                reconciled_transactions.c.residence_id == residence_id,
            )
        )
    assert isinstance(value, UUID)
    return value


def test_expense_import_preserves_negative_observation_amount(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, operator_id = _household(engine)
    account_id = _account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
    )
    reconciled_id = _reconciled(
        engine,
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        amount=Decimal("-87.65"),
    )
    store = BankingLedgerReviewStore(runtime_engine)
    candidate = store.get_candidate(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
        reconciled_transaction_id=reconciled_id,
    )

    result = store.decide(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
        reconciled_transaction_id=reconciled_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=BankingLedgerReviewDraft(
            source_observation_id=candidate.source_observation_id,
            source_observation_updated_at=candidate.source_observation_updated_at,
            decision=BankingLedgerReviewDecision.IMPORT_AS_EXPENSE,
            financial_account_id=account_id,
        ),
    )

    assert result.movement_id is not None
    with engine.begin() as connection:
        movement = connection.execute(
            select(financial_movements).where(
                financial_movements.c.id == result.movement_id
            )
        ).mappings().one()
    assert movement["amount"] == Decimal("-87.65000000")
    assert movement["result_effect"] == "EXPENSE"
    assert movement["role"] == "STANDARD"


def test_concurrent_same_idempotency_key_replays_one_decision(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, operator_id = _household(engine)
    account_id = _account(
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
    )
    reconciled_id = _reconciled(
        engine,
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        amount=Decimal("64.00"),
    )
    store = BankingLedgerReviewStore(runtime_engine)
    candidate = store.get_candidate(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
        reconciled_transaction_id=reconciled_id,
    )
    draft = BankingLedgerReviewDraft(
        source_observation_id=candidate.source_observation_id,
        source_observation_updated_at=candidate.source_observation_updated_at,
        decision=BankingLedgerReviewDecision.IMPORT_AS_INCOME,
        financial_account_id=account_id,
    )
    key = new_financial_idempotency_key()
    barrier = Barrier(2)

    def _decide() -> BankingLedgerReviewRecord:
        barrier.wait()
        return store.decide(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            reconciled_transaction_id=reconciled_id,
            idempotency_key=key,
            draft=draft,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _index: _decide(), range(2)))

    assert results[0] == results[1]
    assert results[0].movement_id is not None
    with engine.begin() as connection:
        movement_count = connection.scalar(
            select(func.count()).select_from(financial_movements)
        )
    assert movement_count == 1
