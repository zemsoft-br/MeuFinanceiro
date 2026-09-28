from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.schema import (
    household_memberships,
    identity_operators,
)

NOW = datetime(2026, 8, 11, 2, 15, tzinfo=UTC)


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


def _account_values(
    *,
    account_id: UUID,
    installation_id: UUID,
    residence_id: UUID,
    owner_operator_id: UUID,
) -> dict[str, object]:
    return {
        "id": account_id,
        "installation_id": installation_id,
        "residence_id": residence_id,
        "owner_operator_id": owner_operator_id,
        "visibility_scope": "PERSONAL",
        "account_type": "CHECKING",
        "custom_type_name": None,
        "name": "Direct synthetic account",
        "currency": "BRL",
        "status": "ACTIVE",
        "created_at": NOW,
        "updated_at": NOW,
        "archived_at": None,
    }


def test_runtime_insert_cannot_spoof_another_active_member_as_owner(
    engine: Engine,
    runtime_engine: Engine,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    create_canonical_residences(installation_id, (residence_id,))

    with engine.begin() as connection:
        current_operator_id = connection.scalar(
            select(household_memberships.c.operator_id).where(
                household_memberships.c.residence_id == residence_id,
                household_memberships.c.status == "active",
            )
        )
        assert isinstance(current_operator_id, UUID)

        other_operator_id = uuid4()
        connection.execute(
            insert(identity_operators).values(
                id=other_operator_id,
                installation_id=installation_id,
                login_name="direct-other-member",
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
                operator_id=other_operator_id,
                role="member",
                status="active",
                is_primary=False,
                created_at=NOW,
                updated_at=NOW,
            )
        )

    with pytest.raises(DBAPIError):
        with runtime_engine.begin() as connection:
            _set_context(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=current_operator_id,
            )
            connection.execute(
                insert(financial_accounts).values(
                    **_account_values(
                        account_id=uuid4(),
                        installation_id=installation_id,
                        residence_id=residence_id,
                        owner_operator_id=other_operator_id,
                    )
                )
            )


def test_database_rejects_non_uuid4_account_id_even_for_valid_owner_context(
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

    invalid_id = uuid5(NAMESPACE_DNS, "synthetic-financial-account")
    assert invalid_id.version == 5

    with pytest.raises(DBAPIError):
        with runtime_engine.begin() as connection:
            _set_context(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=owner_operator_id,
            )
            connection.execute(
                insert(financial_accounts).values(
                    **_account_values(
                        account_id=invalid_id,
                        installation_id=installation_id,
                        residence_id=residence_id,
                        owner_operator_id=owner_operator_id,
                    )
                )
            )


def test_runtime_insert_cannot_create_archived_account_directly(
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

    values = _account_values(
        account_id=uuid4(),
        installation_id=installation_id,
        residence_id=residence_id,
        owner_operator_id=owner_operator_id,
    )
    values["status"] = "ARCHIVED"
    values["archived_at"] = NOW

    with pytest.raises(DBAPIError):
        with runtime_engine.begin() as connection:
            _set_context(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=owner_operator_id,
            )
            connection.execute(insert(financial_accounts).values(**values))
