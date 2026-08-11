from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    FinancialCategoryDraft,
    FinancialVisibilityScope,
)
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence import (
    FinancialCategoryAccessError,
    FinancialCategoryNotFoundError,
    FinancialCategoryParentNotFoundError,
    FinancialCategoryStore,
)
from meufinanceiro_persistence.financial_category_schema import financial_categories
from meufinanceiro_persistence.schema import (
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
)

NOW = datetime(2026, 8, 11, 2, 45, tzinfo=UTC)


@pytest.fixture
def store(runtime_engine: Engine) -> FinancialCategoryStore:
    return FinancialCategoryStore(runtime_engine)


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
                name="Synthetic category household",
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
                    login_name=f"category-member-{index}",
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
    return installation_id, residence_id, operator_ids


def _draft(
    *,
    name: str,
    scope: FinancialVisibilityScope,
    parent_id: UUID | None = None,
) -> FinancialCategoryDraft:
    return FinancialCategoryDraft(
        name=name,
        visibility_scope=scope,
        parent_id=parent_id,
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


def test_category_tree_supports_multiple_depths_without_movement_semantics(
    engine: Engine,
    store: FinancialCategoryStore,
) -> None:
    installation_id, residence_id, operators = _create_household(engine)
    owner_id = operators[0]

    root = store.create_category(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        draft=_draft(name="Alimentação", scope=FinancialVisibilityScope.HOUSEHOLD),
    )
    child = store.create_category(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        draft=_draft(
            name="Mercado",
            scope=FinancialVisibilityScope.HOUSEHOLD,
            parent_id=root.id,
        ),
    )
    grandchild = store.create_category(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        draft=_draft(
            name="Hortifruti",
            scope=FinancialVisibilityScope.HOUSEHOLD,
            parent_id=child.id,
        ),
    )

    assert root.parent_id is None
    assert child.parent_id == root.id
    assert grandchild.parent_id == child.id
    assert grandchild.status.value == "ACTIVE"
    assert not hasattr(grandchild, "movement_type")
    assert not hasattr(grandchild, "kind")

    listed = store.list_categories(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
    )
    assert {record.id for record in listed} == {root.id, child.id, grandchild.id}


def test_personal_category_is_hidden_from_household_administrator(
    engine: Engine,
    store: FinancialCategoryStore,
) -> None:
    installation_id, residence_id, operators = _create_household(
        engine,
        roles=("owner", "administrator"),
    )
    owner_id, administrator_id = operators
    created = store.create_category(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        draft=_draft(name="Pessoal", scope=FinancialVisibilityScope.PERSONAL),
    )

    assert store.list_categories(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=administrator_id,
    ) == ()
    with pytest.raises(FinancialCategoryNotFoundError):
        store.get_category(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=administrator_id,
            category_id=created.id,
        )


def test_household_category_is_visible_to_other_active_member(
    engine: Engine,
    store: FinancialCategoryStore,
) -> None:
    installation_id, residence_id, operators = _create_household(engine)
    owner_id, member_id = operators
    created = store.create_category(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        draft=_draft(name="Casa", scope=FinancialVisibilityScope.HOUSEHOLD),
    )

    visible = store.list_categories(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=member_id,
    )
    assert [record.id for record in visible] == [created.id]


def test_child_cannot_attach_to_other_owner_household_tree(
    engine: Engine,
    store: FinancialCategoryStore,
) -> None:
    installation_id, residence_id, operators = _create_household(engine)
    owner_id, member_id = operators
    root = store.create_category(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        draft=_draft(name="Raiz", scope=FinancialVisibilityScope.HOUSEHOLD),
    )

    with pytest.raises(FinancialCategoryParentNotFoundError):
        store.create_category(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=member_id,
            draft=_draft(
                name="Filho indevido",
                scope=FinancialVisibilityScope.HOUSEHOLD,
                parent_id=root.id,
            ),
        )


def test_disabled_membership_fails_closed(
    engine: Engine,
    store: FinancialCategoryStore,
) -> None:
    installation_id, residence_id, operators = _create_household(engine)
    member_id = operators[1]
    with engine.begin() as connection:
        connection.execute(
            update(household_memberships)
            .where(
                household_memberships.c.residence_id == residence_id,
                household_memberships.c.operator_id == member_id,
            )
            .values(status="disabled", updated_at=NOW)
        )

    with pytest.raises(FinancialCategoryAccessError):
        store.list_categories(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=member_id,
        )


def test_cross_residence_creation_fails_closed(
    engine: Engine,
    store: FinancialCategoryStore,
) -> None:
    installation_id, _residence_id, operators = _create_household(engine)
    owner_id = operators[0]
    foreign_residence_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            insert(household_residences).values(
                id=foreign_residence_id,
                installation_id=installation_id,
                name="Foreign category household",
                status="active",
                created_at=NOW,
                updated_at=NOW,
            )
        )

    with pytest.raises(FinancialCategoryAccessError):
        store.create_category(
            installation_id=installation_id,
            residence_id=foreign_residence_id,
            operator_id=owner_id,
            draft=_draft(name="Inválida", scope=FinancialVisibilityScope.PERSONAL),
        )


def test_runtime_role_cannot_update_move_disable_or_delete_category(
    engine: Engine,
    runtime_engine: Engine,
    store: FinancialCategoryStore,
) -> None:
    installation_id, residence_id, operators = _create_household(engine)
    owner_id = operators[0]
    created = store.create_category(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=owner_id,
        draft=_draft(name="Imutável por enquanto", scope=FinancialVisibilityScope.PERSONAL),
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
                update(financial_categories)
                .where(financial_categories.c.id == created.id)
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
                delete(financial_categories).where(financial_categories.c.id == created.id)
            )
