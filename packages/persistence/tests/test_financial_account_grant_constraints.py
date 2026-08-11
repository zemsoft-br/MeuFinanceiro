from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    FinancialAccountDraft,
    FinancialAccountType,
    FinancialVisibilityScope,
)
from sqlalchemy import insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from meufinanceiro_persistence import FinancialAccountStore
from meufinanceiro_persistence.financial_account_schema import financial_account_grants
from meufinanceiro_persistence.schema import (
    household_memberships,
    identity_operators,
)

NOW = datetime(2026, 8, 11, 2, 20, tzinfo=UTC)


def test_grant_cannot_target_personal_account(
    engine: Engine,
    runtime_engine: Engine,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    create_canonical_residences(installation_id, (residence_id,))

    with engine.begin() as connection:
        owner_operator_id = connection.scalar(
            select(household_memberships.c.operator_id).where(
                household_memberships.c.residence_id == residence_id,
                household_memberships.c.status == "active",
            )
        )
        assert isinstance(owner_operator_id, UUID)

        member_operator_id = uuid4()
        connection.execute(
            insert(identity_operators).values(
                id=member_operator_id,
                installation_id=installation_id,
                login_name="grant-constraint-member",
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
                operator_id=member_operator_id,
                role="member",
                status="active",
                is_primary=False,
                created_at=NOW,
                updated_at=NOW,
            )
        )

    store = FinancialAccountStore(runtime_engine)
    account = store.create_account(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_operator_id,
        draft=FinancialAccountDraft(
            name="Conta pessoal sintética",
            currency="BRL",
            account_type=FinancialAccountType.CHECKING,
            visibility_scope=FinancialVisibilityScope.PERSONAL,
        ),
    )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                insert(financial_account_grants).values(
                    id=uuid4(),
                    installation_id=installation_id,
                    residence_id=residence_id,
                    account_id=account.id,
                    owner_operator_id=owner_operator_id,
                    visibility_scope="SHARED",
                    operator_id=member_operator_id,
                    created_at=NOW,
                )
            )
