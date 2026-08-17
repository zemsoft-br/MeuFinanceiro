from __future__ import annotations

from alembic import command
from sqlalchemy import func, inspect, select
from sqlalchemy.engine import Engine

from meufinanceiro_persistence.migrations import build_alembic_config, current_revision

_REVISION = "0017_movement_allocations"
_PREVIOUS = "0016_banking_ledger_review"
_TABLES = (
    "finance.movement_allocation_sets",
    "finance.movement_allocations",
)


def _table_privilege(engine: Engine, role: str, table: str, privilege: str) -> bool:
    with engine.begin() as connection:
        value = connection.scalar(
            select(func.has_table_privilege(role, table, privilege))
        )
    return value is True


def _rls_state(engine: Engine, table: str) -> tuple[bool, bool]:
    schema, name = table.split(".", maxsplit=1)
    with engine.begin() as connection:
        state = connection.exec_driver_sql(
            """
            SELECT c.relrowsecurity, c.relforcerowsecurity
              FROM pg_catalog.pg_class c
              JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = %(schema)s
               AND c.relname = %(name)s
            """,
            {"schema": schema, "name": name},
        ).one()
    return bool(state[0]), bool(state[1])


def test_movement_allocation_migration_downgrades_and_reupgrades(
    database_url: str,
    app_database_user: str,
    engine: Engine,
) -> None:
    assert len(_REVISION) <= 32
    config = build_alembic_config(
        database_url,
        app_database_user=app_database_user,
    )

    try:
        command.downgrade(config, _PREVIOUS)
        assert current_revision(engine) == _PREVIOUS
        assert not inspect(engine).has_table(
            "movement_allocation_sets",
            schema="finance",
        )
        assert not inspect(engine).has_table(
            "movement_allocations",
            schema="finance",
        )

        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
        assert inspect(engine).has_table(
            "movement_allocation_sets",
            schema="finance",
        )
        assert inspect(engine).has_table(
            "movement_allocations",
            schema="finance",
        )

        for table in _TABLES:
            assert _rls_state(engine, table) == (True, True)
            assert _table_privilege(engine, app_database_user, table, "SELECT")
            assert _table_privilege(engine, app_database_user, table, "INSERT")
            assert not _table_privilege(engine, app_database_user, table, "UPDATE")
            assert not _table_privilege(engine, app_database_user, table, "DELETE")

        command.downgrade(config, _PREVIOUS)
        assert current_revision(engine) == _PREVIOUS
        assert not inspect(engine).has_table(
            "movement_allocation_sets",
            schema="finance",
        )
        assert not inspect(engine).has_table(
            "movement_allocations",
            schema="finance",
        )
        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
    finally:
        command.upgrade(config, "head")
