from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from meufinanceiro_persistence.financial_category_schema import financial_categories
from meufinanceiro_persistence.schema import household_memberships

NOW = datetime(2026, 8, 11, 3, 0, tzinfo=UTC)


def _owner_id(engine: Engine, residence_id: UUID) -> UUID:
    with engine.begin() as connection:
        value = connection.scalar(
            select(household_memberships.c.operator_id).where(
                household_memberships.c.residence_id == residence_id,
                household_memberships.c.status == "active",
            )
        )
    assert isinstance(value, UUID)
    return value


def _values(
    *,
    category_id: UUID,
    installation_id: UUID,
    residence_id: UUID,
    owner_operator_id: UUID,
    visibility_scope: str,
    parent_id: UUID | None = None,
) -> dict[str, object]:
    return {
        "id": category_id,
        "installation_id": installation_id,
        "residence_id": residence_id,
        "owner_operator_id": owner_operator_id,
        "visibility_scope": visibility_scope,
        "parent_id": parent_id,
        "name": "Synthetic category",
        "status": "ACTIVE",
        "created_at": NOW,
        "updated_at": NOW,
        "disabled_at": None,
    }


def test_database_rejects_shared_category_scope(
    engine: Engine,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    create_canonical_residences(installation_id, (residence_id,))
    owner_operator_id = _owner_id(engine, residence_id)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                insert(financial_categories).values(
                    **_values(
                        category_id=uuid4(),
                        installation_id=installation_id,
                        residence_id=residence_id,
                        owner_operator_id=owner_operator_id,
                        visibility_scope="SHARED",
                    )
                )
            )


def test_database_rejects_self_parent(
    engine: Engine,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    create_canonical_residences(installation_id, (residence_id,))
    owner_operator_id = _owner_id(engine, residence_id)
    category_id = uuid4()

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                insert(financial_categories).values(
                    **_values(
                        category_id=category_id,
                        installation_id=installation_id,
                        residence_id=residence_id,
                        owner_operator_id=owner_operator_id,
                        visibility_scope="PERSONAL",
                        parent_id=category_id,
                    )
                )
            )


def test_database_rejects_parent_child_visibility_mismatch(
    engine: Engine,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    create_canonical_residences(installation_id, (residence_id,))
    owner_operator_id = _owner_id(engine, residence_id)
    parent_id = uuid4()

    with engine.begin() as connection:
        connection.execute(
            insert(financial_categories).values(
                **_values(
                    category_id=parent_id,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    owner_operator_id=owner_operator_id,
                    visibility_scope="PERSONAL",
                )
            )
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                insert(financial_categories).values(
                    **_values(
                        category_id=uuid4(),
                        installation_id=installation_id,
                        residence_id=residence_id,
                        owner_operator_id=owner_operator_id,
                        visibility_scope="HOUSEHOLD",
                        parent_id=parent_id,
                    )
                )
            )
