from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    FinancialAccountDraft,
    FinancialAccountType,
    FinancialVisibilityScope,
    new_financial_idempotency_key,
)
from meufinanceiro_security.envelope import SecretCipher
from meufinanceiro_security.keyring import create_keyring
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection, Engine

from meufinanceiro_persistence import (
    BankingIntegrationStore,
    BankingLedgerReviewAccessError,
    BankingLedgerReviewDecision,
    BankingLedgerReviewDraft,
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

_NOW = datetime(2026, 8, 16, 6, 0, tzinfo=UTC)


def _household(engine: Engine) -> tuple[UUID, UUID, UUID, UUID]:
    installation_id = uuid4()
    residence_id = uuid4()
    owner_id = uuid4()
    member_id = uuid4()
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
            insert(household_residences).values(
                id=residence_id,
                installation_id=installation_id,
                name="Synthetic authorization review residence",
                status="active",
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        for index, (operator_id, role) in enumerate(
            ((owner_id, "owner"), (member_id, "member"))
        ):
            connection.execute(
                insert(identity_operators).values(
                    id=operator_id,
                    installation_id=installation_id,
                    login_name=f"ledger-review-auth-{index}",
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
                insert(household_memberships).values(
                    id=uuid4(),
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                    role=role,
                    status="active",
                    is_primary=index == 0,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
    return installation_id, residence_id, owner_id, member_id


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
                number_mask="2468",
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
                description="Synthetic authorization transaction",
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


def _set_context(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
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
            func.set_config(
                "app.current_operator_id",
                str(operator_id),
                True,
            ),
        )
    )


def test_disabled_membership_fails_closed_for_candidate_lookup(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, _owner_id, member_id = _household(engine)
    reconciled_id = _reconciled(
        engine,
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        amount=Decimal("31.00"),
    )
    store = BankingLedgerReviewStore(runtime_engine)

    candidate = store.get_candidate(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=member_id,
        reconciled_transaction_id=reconciled_id,
    )
    assert candidate.reconciled_transaction_id == reconciled_id

    with engine.begin() as connection:
        connection.execute(
            update(household_memberships)
            .where(
                household_memberships.c.residence_id == residence_id,
                household_memberships.c.operator_id == member_id,
            )
            .values(status="disabled", updated_at=_NOW)
        )

    with pytest.raises(BankingLedgerReviewAccessError):
        store.get_candidate(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=member_id,
            reconciled_transaction_id=reconciled_id,
        )


def test_personal_movement_link_is_not_visible_to_other_member(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, member_id = _household(engine)
    owner_account = FinancialAccountStore(runtime_engine).create_account(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        draft=FinancialAccountDraft(
            name="Synthetic owner personal account",
            currency="BRL",
            account_type=FinancialAccountType.CHECKING,
            visibility_scope=FinancialVisibilityScope.PERSONAL,
        ),
    )
    reconciled_id = _reconciled(
        engine,
        runtime_engine,
        installation_id=installation_id,
        residence_id=residence_id,
        amount=Decimal("73.40"),
    )
    store = BankingLedgerReviewStore(runtime_engine)
    candidate = store.get_candidate(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        reconciled_transaction_id=reconciled_id,
    )
    created = store.decide(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        reconciled_transaction_id=reconciled_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=BankingLedgerReviewDraft(
            source_observation_id=candidate.source_observation_id,
            source_observation_updated_at=candidate.source_observation_updated_at,
            decision=BankingLedgerReviewDecision.IMPORT_AS_INCOME,
            financial_account_id=owner_account.id,
        ),
    )
    assert created.movement_id is not None

    with runtime_engine.begin() as connection:
        _set_context(
            connection,
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=member_id,
        )
        visible_links = connection.scalar(
            select(func.count()).select_from(reconciled_transaction_ledger_links)
        )
        visible_movements = connection.scalar(
            select(func.count()).select_from(financial_movements)
        )

    assert visible_links == 0
    assert visible_movements == 0
