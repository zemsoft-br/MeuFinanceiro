from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    FinancialAccountDraft,
    FinancialAccountType,
    FinancialVisibilityScope,
)
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence import (
    FinancialAccountAccessError,
    FinancialAccountNotFoundError,
    FinancialAccountStore,
)
from meufinanceiro_persistence.financial_account_schema import (
    financial_account_grants,
    financial_accounts,
)
from meufinanceiro_persistence.schema import (
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
)

NOW = datetime(2026, 8, 11, 2, 0, tzinfo=UTC)


@pytest.fixture
def store(runtime_engine: Engine) -> FinancialAccountStore:
    return FinancialAccountStore(runtime_engine)


def _create_household(
    engine: Engine,
    *,
    roles: tuple[str, ...] = ("owner", "member"),
) -> tuple[UUID, UUID, tuple[UUID, ...]]:
    installation_id = uuid4()
    residence_id = uuid4()
    operator_ids = tuple(uuid4() for _ in roles)
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
                name="Synthetic household",
                status="active",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        for index, (operator_id, role) in enumerate(zip(operator_ids, roles, strict=True)):
            connection.execute(
                insert(identity_operators).values(
                    id=operator_id,
                    installation_id=installation_id,
                    login_name=f"synthetic-{index}",
                    password_hash="synthetic-password-hash-material-000000000000",
                    role="installation_admin" if index == 0 else "member",
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
    return installation_id, residence_id, operator_ids


def _draft(scope: FinancialVisibilityScope) -> FinancialAccountDraft:
    return FinancialAccountDraft(
        name="Conta sintética",
        currency="BRL",
        account_type=FinancialAccountType.CHECKING,
        visibility_scope=scope,
    )


def _set_context(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
) -> None:
    connection.execute(
        select(
            func.set_config("app.current_installation_id", str(installation_id), True),
            func.set_config("app.current_residence_id", str(residence_id), True),
            func.set_config("app.current_operator_id", str(operator_id), True),
        )
    )


def test_create_list_and_get_account_without_balance_fields(
    engine: Engine,
    store: FinancialAccountStore,
) -> None:
    installation_id, residence_id, operators = _create_household(engine)
    owner_id = operators[0]

    created = store.create_account(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        draft=_draft(FinancialVisibilityScope.PERSONAL),
    )

    assert created.owner_operator_id == owner_id
    assert created.residence_id == residence_id
    assert created.currency == "BRL"
    assert created.status.value == "ACTIVE"
    assert created.archived_at is None
    assert not hasattr(created, "balance")
    assert not hasattr(created, "initial_balance")

    listed = store.list_accounts(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
    )
    assert [record.id for record in listed] == [created.id]

    fetched = store.get_account(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        account_id=created.id,
    )
    assert fetched == created


def test_personal_account_is_hidden_from_other_active_member_even_administrator(
    engine: Engine,
    store: FinancialAccountStore,
) -> None:
    installation_id, residence_id, operators = _create_household(
        engine,
        roles=("owner", "administrator"),
    )
    owner_id, administrator_id = operators
    created = store.create_account(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        draft=_draft(FinancialVisibilityScope.PERSONAL),
    )

    assert store.list_accounts(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=administrator_id,
    ) == ()
    with pytest.raises(FinancialAccountNotFoundError):
        store.get_account(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=administrator_id,
            account_id=created.id,
        )


def test_household_account_is_visible_to_other_active_member(
    engine: Engine,
    store: FinancialAccountStore,
) -> None:
    installation_id, residence_id, operators = _create_household(engine)
    owner_id, member_id = operators
    created = store.create_account(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        draft=_draft(FinancialVisibilityScope.HOUSEHOLD),
    )

    visible = store.list_accounts(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=member_id,
    )
    assert [record.id for record in visible] == [created.id]


def test_shared_account_requires_explicit_grant_for_other_member(
    engine: Engine,
    store: FinancialAccountStore,
) -> None:
    installation_id, residence_id, operators = _create_household(engine)
    owner_id, member_id = operators
    created = store.create_account(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        draft=_draft(FinancialVisibilityScope.SHARED),
    )

    assert store.list_accounts(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=member_id,
    ) == ()

    with engine.begin() as connection:
        connection.execute(
            insert(financial_account_grants).values(
                id=uuid4(),
                installation_id=installation_id,
                residence_id=residence_id,
                account_id=created.id,
                owner_operator_id=owner_id,
                operator_id=member_id,
                created_at=NOW,
            )
        )

    visible = store.list_accounts(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=member_id,
    )
    assert [record.id for record in visible] == [created.id]


def test_disabled_membership_fails_closed_even_for_household_account(
    engine: Engine,
    store: FinancialAccountStore,
) -> None:
    installation_id, residence_id, operators = _create_household(engine)
    owner_id, member_id = operators
    store.create_account(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        draft=_draft(FinancialVisibilityScope.HOUSEHOLD),
    )
    with engine.begin() as connection:
        connection.execute(
            update(household_memberships)
            .where(
                household_memberships.c.residence_id == residence_id,
                household_memberships.c.operator_id == member_id,
            )
            .values(status="disabled", updated_at=NOW)
        )

    with pytest.raises(FinancialAccountAccessError):
        store.list_accounts(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=member_id,
        )


def test_cross_residence_context_fails_closed(
    engine: Engine,
    store: FinancialAccountStore,
) -> None:
    installation_id, residence_id, operators = _create_household(engine)
    owner_id = operators[0]
    foreign_residence_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            insert(household_residences).values(
                id=foreign_residence_id,
                installation_id=installation_id,
                name="Foreign synthetic household",
                status="active",
                created_at=NOW,
                updated_at=NOW,
            )
        )

    with pytest.raises(FinancialAccountAccessError):
        store.create_account(
            installation_id=installation_id,
            residence_id=foreign_residence_id,
            operator_id=owner_id,
            draft=_draft(FinancialVisibilityScope.PERSONAL),
        )


def test_runtime_role_cannot_update_delete_accounts_or_insert_grants(
    engine: Engine,
    runtime_engine: Engine,
    store: FinancialAccountStore,
) -> None:
    installation_id, residence_id, operators = _create_household(engine)
    owner_id, member_id = operators
    created = store.create_account(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        draft=_draft(FinancialVisibilityScope.SHARED),
    )

    with pytest.raises(DBAPIError):
        with runtime_engine.begin() as connection:
            _set_context(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=owner_id,
            )
            connection.execute(
                update(financial_accounts)
                .where(financial_accounts.c.id == created.id)
                .values(name="Mutação proibida")
            )

    with pytest.raises(DBAPIError):
        with runtime_engine.begin() as connection:
            _set_context(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=owner_id,
            )
            connection.execute(
                delete(financial_accounts).where(financial_accounts.c.id == created.id)
            )

    with pytest.raises(DBAPIError):
        with runtime_engine.begin() as connection:
            _set_context(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=owner_id,
            )
            connection.execute(
                insert(financial_account_grants).values(
                    id=uuid4(),
                    installation_id=installation_id,
                    residence_id=residence_id,
                    account_id=created.id,
                    owner_operator_id=owner_id,
                    operator_id=member_id,
                    created_at=NOW,
                )
            )
