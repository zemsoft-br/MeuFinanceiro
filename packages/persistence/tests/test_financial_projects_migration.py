"""Migration and runtime-security proofs for financial projects (#262).

Requires a disposable PostgreSQL database with a separate NOSUPERUSER runtime
role. No mocks and no GitHub Actions. This test never touches real user data.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from meufinanceiro_finance import (
    FinancialMovementDraft,
    FinancialResultEffect,
    Money,
    new_financial_idempotency_key,
)
from sqlalchemy import Engine, func, inspect, insert, select
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementStore,
    _set_context,
)
from meufinanceiro_persistence.financial_project_schema import (
    financial_project_link_revisions,
    financial_projects,
)
from meufinanceiro_persistence.migrations import (
    build_alembic_config,
    current_revision,
)

if TYPE_CHECKING:
    from conftest import BudgetWorld

_REVISION = "0029_financial_projects"
_PREVIOUS = "0028_financial_goals"
_TABLES = ("finance.projects", "finance.project_movement_link_revisions")
_FUNCTIONS = (
    "finance.enforce_project_row()",
    "finance.enforce_project_link_revision()",
    "finance.lock_project_account_transition()",
    "finance.reject_project_link_history_mutation()",
)


def _rls(engine: Engine, table: str) -> tuple[bool, bool]:
    schema, name = table.split(".", 1)
    with engine.begin() as connection:
        row = connection.exec_driver_sql(
            "SELECT c.relrowsecurity, c.relforcerowsecurity "
            "FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %(s)s AND c.relname = %(t)s",
            {"s": schema, "t": name},
        ).one()
    return (bool(row[0]), bool(row[1]))


def _privilege(engine: Engine, role: str, table: str, name: str) -> bool:
    with engine.begin() as connection:
        return (
            connection.scalar(select(func.has_table_privilege(role, table, name)))
            is True
        )


def test_project_revision_belongs_to_single_alembic_head() -> None:
    config = build_alembic_config(
        "postgresql+psycopg://unused:unused@localhost/unused",
        app_database_user="unused_role",
    )
    directory = ScriptDirectory.from_config(config)
    heads = directory.get_heads()
    assert len(heads) == 1
    assert directory.get_revision(_REVISION).down_revision == _PREVIOUS


def test_project_tables_grants_rls_and_symmetric_downgrade(
    database_url: str, app_database_user: str, engine: Engine
) -> None:
    config = build_alembic_config(database_url, app_database_user=app_database_user)
    before = {
        c["name"] for c in inspect(engine).get_columns("movements", schema="finance")
    }
    assert current_revision(engine) == _REVISION
    for table in _TABLES:
        assert _rls(engine, table) == (True, True)
        assert _privilege(engine, app_database_user, table, "SELECT")
        assert _privilege(engine, app_database_user, table, "INSERT")
        assert not _privilege(engine, app_database_user, table, "DELETE")
        assert not _privilege(engine, app_database_user, table, "TRUNCATE")
    assert not _privilege(engine, app_database_user, _TABLES[1], "UPDATE")
    assert not _privilege(engine, app_database_user, _TABLES[0], "UPDATE")
    for name in (
        "title",
        "description",
        "planned_amount",
        "target_date",
        "version",
        "updated_at",
        "updated_by_operator_id",
    ):
        with engine.begin() as connection:
            assert connection.scalar(
                select(
                    func.has_column_privilege(
                        app_database_user, _TABLES[0], name, "UPDATE"
                    )
                )
            )
    with engine.begin() as connection:
        roles = connection.exec_driver_sql(
            "SELECT rolsuper, rolbypassrls "
            "FROM pg_catalog.pg_roles WHERE rolname=%(r)s",
            {"r": app_database_user},
        ).one()
    assert tuple(roles) == (False, False)

    try:
        command.downgrade(config, _PREVIOUS)
        assert current_revision(engine) == _PREVIOUS
        for table in ("projects", "project_movement_link_revisions"):
            assert not inspect(engine).has_table(table, schema="finance")
        with engine.begin() as connection:
            for signature in _FUNCTIONS:
                assert (
                    connection.scalar(select(func.to_regprocedure(signature))) is None
                )
        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
        assert {
            c["name"]
            for c in inspect(engine).get_columns("movements", schema="finance")
        } == before
    finally:
        command.upgrade(config, "head")


def _project(
    connection: object,
    world: BudgetWorld,
    *,
    scope: str = "HOUSEHOLD",
) -> UUID:
    project_id = uuid4()
    connection.execute(  # type: ignore[attr-defined]
        insert(financial_projects).values(
            id=project_id,
            installation_id=world.installation_id,
            residence_id=world.residence_id,
            owner_operator_id=world.owner_id,
            visibility_scope=scope,
            title="Reforma",
            description=None,
            currency="BRL",
            planned_amount=Decimal("1000"),
            target_date=None,
            version=1,
            idempotency_key=uuid4(),
            request_digest="a" * 64,
            updated_by_operator_id=world.owner_id,
            created_at=func.transaction_timestamp(),
            updated_at=func.transaction_timestamp(),
        )
    )
    return project_id


def _revision(
    connection: object,
    world: BudgetWorld,
    movement_id: UUID,
    account_id: UUID,
    project_id: UUID | None,
    *,
    predecessor: UUID | None = None,
    revision: int = 1,
    scope: str = "HOUSEHOLD",
) -> UUID:
    event_id = uuid4()
    connection.execute(  # type: ignore[attr-defined]
        insert(financial_project_link_revisions).values(
            id=event_id,
            installation_id=world.installation_id,
            residence_id=world.residence_id,
            movement_id=movement_id,
            account_id=account_id,
            currency="BRL",
            result_effect="EXPENSE",
            role="STANDARD",
            owner_operator_id=world.owner_id,
            visibility_scope=scope,
            project_id=project_id,
            supersedes_id=predecessor,
            revision=revision,
            actor_operator_id=world.owner_id,
            idempotency_key=uuid4(),
            request_digest="b" * 64,
            created_at=func.transaction_timestamp(),
        )
    )
    return event_id


def test_project_link_chain_is_append_only_and_never_forks(
    budget_world: BudgetWorld,
) -> None:
    world = budget_world
    account_id = world.account()
    movement = FinancialMovementStore(world.runtime).create_movement(
        **world.scope(),
        idempotency_key=new_financial_idempotency_key(),
        draft=FinancialMovementDraft(
            account_id=account_id,
            amount=Money(Decimal("-25"), "BRL"),
            result_effect=FinancialResultEffect.EXPENSE,
            effective_date=date(2026, 10, 8),
            competence_date=date(2026, 10, 8),
            description="Material de obra",
        ),
    )
    with world.runtime.begin() as connection:
        _set_context(connection, **world.scope())
        first_project = _project(connection, world)
        second_project = _project(connection, world)
        first = _revision(connection, world, movement.id, account_id, first_project)
    with world.runtime.begin() as connection:
        _set_context(connection, **world.scope())
        second = _revision(
            connection,
            world,
            movement.id,
            account_id,
            second_project,
            predecessor=first,
            revision=2,
        )
    with world.runtime.begin() as connection:
        _set_context(connection, **world.scope())
        unlinked = _revision(
            connection,
            world,
            movement.id,
            account_id,
            None,
            predecessor=second,
            revision=3,
        )
    assert unlinked != second
    with world.runtime.begin() as connection:
        _set_context(connection, **world.scope())
        assert (
            connection.scalar(
                select(func.count()).select_from(financial_project_link_revisions)
            )
            == 3
        )
        assert (
            connection.scalar(
                select(financial_project_link_revisions.c.project_id).where(
                    financial_project_link_revisions.c.id == unlinked
                )
            )
            is None
        )
    with pytest.raises(DBAPIError):
        with world.runtime.begin() as connection:
            _set_context(connection, **world.scope())
            _revision(
                connection,
                world,
                movement.id,
                account_id,
                first_project,
                predecessor=first,
                revision=2,
            )
    with pytest.raises(DBAPIError):
        with world.runtime.begin() as connection:
            _set_context(connection, **world.scope())
            _revision(connection, world, movement.id, account_id, first_project)
