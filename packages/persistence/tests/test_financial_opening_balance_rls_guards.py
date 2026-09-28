from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from meufinanceiro_finance import (
    FinancialAccountDraft,
    FinancialAccountType,
    FinancialVisibilityScope,
)
from sqlalchemy import func, insert, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.financial_account_store import FinancialAccountStore
from meufinanceiro_persistence.financial_opening_balance_schema import (
    financial_opening_balances,
)
from meufinanceiro_persistence.schema import (
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
)

NOW = datetime(2026, 8, 11, 4, 0, tzinfo=UTC)


def _set_context(
    connection: Connection,
    *,
    installation_id: object,
    residence_id: object,
    operator_id: object,
) -> None:
    connection.execute(
        select(
            func.set_config("app.current_installation_id", str(installation_id), True),
            func.set_config("app.current_residence_id", str(residence_id), True),
            func.set_config("app.current_operator_id", str(operator_id), True),
        )
    )


def test_visible_household_account_does_not_allow_non_owner_anchor_insert(
    engine: Engine,
    runtime_engine: Engine,
) -> None:
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
                name="Opening RLS household",
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
                    login_name=f"opening-rls-{index}",
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

    account = FinancialAccountStore(runtime_engine).create_account(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        draft=FinancialAccountDraft(
            name="Household account",
            currency="BRL",
            account_type=FinancialAccountType.CHECKING,
            visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
        ),
    )

    with pytest.raises(DBAPIError):
        with runtime_engine.begin() as connection:
            _set_context(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=member_id,
            )
            connection.execute(
                insert(financial_opening_balances).values(
                    id=uuid4(),
                    installation_id=installation_id,
                    residence_id=residence_id,
                    account_id=account.id,
                    currency="BRL",
                    amount=Decimal("100"),
                    effective_date=date(2026, 8, 1),
                    created_by_operator_id=member_id,
                    created_at=NOW,
                )
            )
