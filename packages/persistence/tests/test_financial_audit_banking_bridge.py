from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
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
    BankingLedgerReviewStore,
    ExternalAccountSnapshot,
    FinancialAuditStore,
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
from meufinanceiro_persistence.schema import (
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
)

_NOW = datetime(2026, 8, 18, 3, 0, tzinfo=UTC)


def _create_household(engine: Engine) -> tuple[UUID, UUID, UUID]:
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
                login_name="audit-banking-owner",
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
                name="Synthetic banking audit residence",
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


def _create_reconciled_transaction(
    engine: Engine,
    runtime_engine: Engine,
    *,
    installation_id: UUID,
    residence_id: UUID,
) -> UUID:
    banking = BankingIntegrationStore(
        runtime_engine,
        SecretCipher(create_keyring()),
    )
    configured = banking.create_configuration(
        installation_id=installation_id,
        provider="pluggy",
        client_id="synthetic-audit-client-id",
        client_secret="synthetic-audit-client-secret",
    )
    banking.set_configuration_state(
        installation_id=installation_id,
        provider="pluggy",
        expected_revision=configured.configuration_revision,
        state=ProviderConfigurationState.ENABLED,
    )
    stored_connection = banking.register_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        provider="pluggy",
        external_connection_id=f"audit-connection-{uuid4()}",
        status=StoredConnectionStatus.AVAILABLE,
        requires_user_action=False,
    )
    external_account_id = f"audit-account-{uuid4()}"
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
                external_resource_id=f"audit-transaction-{uuid4()}",
                status=StoredTransactionObservationStatus.CONFIRMED,
                provider_updated_at=_NOW,
                effective_date=date(2026, 8, 18),
                amount=Decimal("321.45"),
                currency="BRL",
                description="Synthetic banking audit import",
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
        reconciled_id = connection.scalar(
            select(reconciled_transactions.c.id).where(
                reconciled_transactions.c.connection_id == stored_connection.id,
                reconciled_transactions.c.residence_id == residence_id,
            )
        )
    assert isinstance(reconciled_id, UUID)
    return reconciled_id


def test_explicit_banking_import_emits_one_movement_audit_event(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, operator_id = _create_household(engine)
    account = FinancialAccountStore(runtime_engine).create_account(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
        draft=FinancialAccountDraft(
            name="Synthetic banking audit account",
            currency="BRL",
            account_type=FinancialAccountType.CHECKING,
            visibility_scope=FinancialVisibilityScope.PERSONAL,
        ),
    )
    reconciled_id = _create_reconciled_transaction(
        engine,
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
    )
    store = BankingLedgerReviewStore(runtime_engine)
    candidate = store.get_candidate(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
        reconciled_transaction_id=reconciled_id,
    )
    key = new_financial_idempotency_key()
    draft = BankingLedgerReviewDraft(
        source_observation_id=candidate.source_observation_id,
        source_observation_updated_at=candidate.source_observation_updated_at,
        decision=BankingLedgerReviewDecision.IMPORT_AS_INCOME,
        financial_account_id=account.id,
    )

    created = store.decide(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
        reconciled_transaction_id=reconciled_id,
        idempotency_key=key,
        draft=draft,
    )
    replay = store.decide(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
        reconciled_transaction_id=reconciled_id,
        idempotency_key=key,
        draft=draft,
    )
    assert replay == created
    assert created.movement_id is not None

    events = FinancialAuditStore(runtime_engine).list_events(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
    )
    movement_events = [
        event
        for event in events
        if event.event_type.value == "MOVEMENT_CREATED"
        and event.subject_id == created.movement_id
    ]
    assert len(movement_events) == 1
    assert movement_events[0].subject_type.value == "MOVEMENT"
    assert movement_events[0].related_subject_id is None
