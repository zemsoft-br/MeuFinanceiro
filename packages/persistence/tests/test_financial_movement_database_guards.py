from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
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
from sqlalchemy import insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from meufinanceiro_persistence.financial_account_store import FinancialAccountStore
from meufinanceiro_persistence.financial_movement_schema import financial_movements
from meufinanceiro_persistence.financial_movement_store import FinancialMovementStore
from meufinanceiro_persistence.schema import (
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
)

NOW = datetime(2026, 8, 11, 5, 45, tzinfo=UTC)


def _create_owner_and_account(
    engine: Engine,
    runtime_engine: Engine,
) -> tuple[UUID, UUID, UUID, UUID]:
    installation_id = uuid4()
    residence_id = uuid4()
    owner_id = uuid4()
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
            insert(identity_operators).values(
                id=owner_id,
                installation_id=installation_id,
                login_name="movement-db-owner",
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
            insert(household_residences).values(
                id=residence_id,
                installation_id=installation_id,
                name="Movement database guards",
                status="active",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            insert(household_memberships).values(
                id=uuid4(),
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=owner_id,
                role="owner",
                status="active",
                is_primary=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    account_id = (
        FinancialAccountStore(runtime_engine)
        .create_account(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=owner_id,
            draft=FinancialAccountDraft(
                name="Movement guard account",
                currency="BRL",
                account_type=FinancialAccountType.CHECKING,
                visibility_scope=FinancialVisibilityScope.PERSONAL,
            ),
        )
        .id
    )
    return installation_id, residence_id, owner_id, account_id


def test_database_rejects_invalid_standard_sign_even_outside_store(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, account_id = _create_owner_and_account(
        engine,
        runtime_engine,
    )

    with pytest.raises(IntegrityError) as error:
        with engine.begin() as connection:
            connection.execute(
                insert(financial_movements).values(
                    id=uuid4(),
                    installation_id=installation_id,
                    residence_id=residence_id,
                    account_id=account_id,
                    currency="BRL",
                    amount=Decimal("-10"),
                    result_effect="INCOME",
                    role="STANDARD",
                    effective_date=date(2026, 8, 10),
                    competence_date=date(2026, 8, 1),
                    description="Sinal inválido",
                    reversal_of_id=None,
                    reversal_target_role=None,
                    reversal_reason=None,
                    created_by_operator_id=owner_id,
                    idempotency_key=uuid4(),
                    request_digest="a" * 64,
                    created_at=NOW,
                )
            )

    diagnostic = getattr(error.value.orig, "diag", None)
    assert getattr(diagnostic, "constraint_name", None) == (
        "ck_finance_movements_standard_sign"
    )


def test_database_trigger_rejects_reversal_amount_not_equal_to_negative_original(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
    installation_id, residence_id, owner_id, account_id = _create_owner_and_account(
        engine,
        runtime_engine,
    )
    original = FinancialMovementStore(runtime_engine).create_movement(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementDraft(
            account_id=account_id,
            amount=Money(Decimal("50"), "BRL"),
            result_effect=FinancialResultEffect.INCOME,
            effective_date=date(2026, 8, 10),
            competence_date=date(2026, 8, 1),
            description="Original sintético",
        ),
    )

    with pytest.raises(IntegrityError) as error:
        with engine.begin() as connection:
            connection.execute(
                insert(financial_movements).values(
                    id=uuid4(),
                    installation_id=installation_id,
                    residence_id=residence_id,
                    account_id=account_id,
                    currency="BRL",
                    amount=Decimal("-49"),
                    result_effect="INCOME",
                    role="REVERSAL",
                    effective_date=date(2026, 8, 11),
                    competence_date=date(2026, 8, 1),
                    description=None,
                    reversal_of_id=original.id,
                    reversal_target_role="STANDARD",
                    reversal_reason="Amount adulterado",
                    created_by_operator_id=owner_id,
                    idempotency_key=uuid4(),
                    request_digest="b" * 64,
                    created_at=NOW,
                )
            )

    diagnostic = getattr(error.value.orig, "diag", None)
    assert getattr(diagnostic, "constraint_name", None) == (
        "ck_finance_movement_reversal_amount"
    )
