from __future__ import annotations

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import func, inspect, select
from sqlalchemy.engine import Engine

from meufinanceiro_persistence.migrations import build_alembic_config, current_revision

_REVISION = "0023_monthly_budgets"
_PREVIOUS = "0022_pending_movement_indexes"
_BUDGETS = "finance.budgets"
_LINES = "finance.budget_lines"
_FUNCTIONS = (
    "finance.enforce_budget_row()",
    "finance.validate_budget_line_row()",
    "finance.validate_budget_closure()",
)
_FORBIDDEN_LEDGER_COLUMNS = {"budget_id", "category_id", "planned_amount"}


def _privilege(engine: Engine, role: str, table: str, privilege: str) -> bool:
    with engine.begin() as connection:
        return (
            connection.scalar(select(func.has_table_privilege(role, table, privilege)))
            is True
        )


def _column_update(engine: Engine, role: str, column: str) -> bool:
    with engine.begin() as connection:
        return (
            connection.scalar(
                select(func.has_column_privilege(role, _BUDGETS, column, "UPDATE"))
            )
            is True
        )


def _rls_state(engine: Engine, table: str) -> tuple[bool, bool]:
    schema, name = table.split(".", maxsplit=1)
    with engine.begin() as connection:
        state = connection.exec_driver_sql(
            "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %(schema)s AND c.relname = %(name)s",
            {"schema": schema, "name": name},
        ).one()
    return bool(state[0]), bool(state[1])


def _policies(engine: Engine, table: str) -> dict[str, str]:
    schema, name = table.split(".", maxsplit=1)
    with engine.begin() as connection:
        rows = connection.exec_driver_sql(
            "SELECT policyname, cmd FROM pg_policies "
            "WHERE schemaname = %(schema)s AND tablename = %(name)s",
            {"schema": schema, "name": name},
        ).all()
    return {str(row[0]): str(row[1]) for row in rows}


def test_revision_id_fits_and_history_has_a_single_head() -> None:
    assert len(_REVISION) <= 32
    config = build_alembic_config(
        "postgresql+psycopg://unused:unused@localhost/unused",
        app_database_user="unused_role",
    )
    directory = ScriptDirectory.from_config(config)
    heads = directory.get_heads()
    assert len(heads) == 1
    assert _REVISION in {
        item.revision for item in directory.walk_revisions(base="base", head=heads[0])
    }
    script = directory.get_revision(_REVISION)
    assert script is not None and script.down_revision == _PREVIOUS


def test_budget_tables_rls_grants_and_symmetric_downgrade(
    database_url: str, app_database_user: str, engine: Engine
) -> None:
    config = build_alembic_config(database_url, app_database_user=app_database_user)
    try:
        command.downgrade(config, _PREVIOUS)
        assert current_revision(engine) == _PREVIOUS
        assert not inspect(engine).has_table("budgets", schema="finance")
        assert not inspect(engine).has_table("budget_lines", schema="finance")
        movement_columns_before = {
            c["name"]
            for c in inspect(engine).get_columns("movements", schema="finance")
        }

        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
        assert inspect(engine).has_table("budgets", schema="finance")
        assert inspect(engine).has_table("budget_lines", schema="finance")

        # The ledger is untouched: no budget column or pointer appears on Movements.
        movement_columns = {
            c["name"]
            for c in inspect(engine).get_columns("movements", schema="finance")
        }
        assert movement_columns == movement_columns_before
        assert not _FORBIDDEN_LEDGER_COLUMNS & movement_columns

        for table in (_BUDGETS, _LINES):
            assert _rls_state(engine, table) == (True, True)
        assert set(_policies(engine, _BUDGETS)) == {
            "finance_budgets_select",
            "finance_budgets_insert",
            "finance_budgets_update",
        }
        assert set(_policies(engine, _LINES)) == {
            "finance_budget_lines_select",
            "finance_budget_lines_insert",
        }

        for table in (_BUDGETS, _LINES):
            assert _privilege(engine, app_database_user, table, "SELECT")
            assert _privilege(engine, app_database_user, table, "INSERT")
            assert not _privilege(engine, app_database_user, table, "DELETE")
            assert not _privilege(engine, app_database_user, table, "TRUNCATE")
        assert not _privilege(engine, app_database_user, _LINES, "UPDATE")
        for column in ("name", "version", "updated_at", "updated_by_operator_id"):
            assert _column_update(engine, app_database_user, column)
        for column in (
            "currency",
            "period_start",
            "date_basis",
            "visibility_scope",
            "owner_operator_id",
            "idempotency_key",
        ):
            assert not _column_update(engine, app_database_user, column)

        command.downgrade(config, _PREVIOUS)
        assert not inspect(engine).has_table("budgets", schema="finance")
        with engine.begin() as connection:
            for function in _FUNCTIONS:
                assert connection.scalar(select(func.to_regprocedure(function))) is None
        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
    finally:
        command.upgrade(config, "head")
