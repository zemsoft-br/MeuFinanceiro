from __future__ import annotations

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import func, inspect, select
from sqlalchemy.engine import Engine

from meufinanceiro_persistence.migrations import build_alembic_config, current_revision

_REVISION = "0025_monthly_recurrences"
_PREVIOUS = "0024_budget_realization_indexes"
_RULES = "finance.recurrences"
_OCCURRENCES = "finance.recurrence_occurrences"
_FUNCTIONS = (
    "finance.enforce_recurrence_row()",
    "finance.validate_recurrence_occurrence_insert()",
    "finance.enforce_recurrence_occurrence_transition()",
)
_FORBIDDEN_LEDGER_COLUMNS = {"recurrence_id", "occurrence_id", "expected_amount"}


def _privilege(engine: Engine, role: str, table: str, privilege: str) -> bool:
    with engine.begin() as connection:
        return (
            connection.scalar(select(func.has_table_privilege(role, table, privilege)))
            is True
        )


def _column_update(engine: Engine, role: str, table: str, column: str) -> bool:
    with engine.begin() as connection:
        return (
            connection.scalar(
                select(func.has_column_privilege(role, table, column, "UPDATE"))
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
    # Later revisions may build on this one; it must stay in the single history.
    assert _REVISION in {
        item.revision for item in directory.walk_revisions(base="base", head=heads[0])
    }
    script = directory.get_revision(_REVISION)
    assert script is not None and script.down_revision == _PREVIOUS


def test_recurrence_tables_rls_grants_and_symmetric_downgrade(
    database_url: str, app_database_user: str, engine: Engine
) -> None:
    config = build_alembic_config(database_url, app_database_user=app_database_user)
    try:
        command.downgrade(config, _PREVIOUS)
        assert current_revision(engine) == _PREVIOUS
        assert not inspect(engine).has_table("recurrences", schema="finance")
        assert not inspect(engine).has_table("recurrence_occurrences", schema="finance")
        movement_columns_before = {
            c["name"]
            for c in inspect(engine).get_columns("movements", schema="finance")
        }

        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
        assert inspect(engine).has_table("recurrences", schema="finance")
        assert inspect(engine).has_table("recurrence_occurrences", schema="finance")

        # The ledger is untouched: no recurrence column or pointer appears on Movements.
        movement_columns = {
            c["name"]
            for c in inspect(engine).get_columns("movements", schema="finance")
        }
        assert movement_columns == movement_columns_before
        assert not _FORBIDDEN_LEDGER_COLUMNS & movement_columns

        for table in (_RULES, _OCCURRENCES):
            assert _rls_state(engine, table) == (True, True)
        assert set(_policies(engine, _RULES)) == {
            "finance_recurrences_select",
            "finance_recurrences_insert",
            "finance_recurrences_update",
        }
        assert set(_policies(engine, _OCCURRENCES)) == {
            "finance_recurrence_occurrences_select",
            "finance_recurrence_occurrences_insert",
            "finance_recurrence_occurrences_update",
        }

        for table in (_RULES, _OCCURRENCES):
            assert _privilege(engine, app_database_user, table, "SELECT")
            assert _privilege(engine, app_database_user, table, "INSERT")
            assert not _privilege(engine, app_database_user, table, "DELETE")
            assert not _privilege(engine, app_database_user, table, "TRUNCATE")
        for column in (
            "description",
            "expected_amount",
            "day_of_month",
            "end_date",
            "status",
            "version",
            "updated_at",
            "updated_by_operator_id",
        ):
            assert _column_update(engine, app_database_user, _RULES, column)
        for column in (
            "currency",
            "start_date",
            "account_id",
            "result_effect",
            "owner_operator_id",
            "idempotency_key",
            "frequency",
        ):
            assert not _column_update(engine, app_database_user, _RULES, column)
        for column in (
            "status",
            "movement_id",
            "realization_idempotency_key",
            "realization_request_digest",
            "realized_at",
            "realized_by_operator_id",
            "skipped_at",
            "superseded_at",
            "updated_at",
        ):
            assert _column_update(engine, app_database_user, _OCCURRENCES, column)
        for column in (
            "expected_amount",
            "description",
            "scheduled_date",
            "period_start",
            "rule_version",
            "recurrence_id",
            "account_id",
            "currency",
        ):
            assert not _column_update(engine, app_database_user, _OCCURRENCES, column)

        command.downgrade(config, _PREVIOUS)
        assert not inspect(engine).has_table("recurrences", schema="finance")
        with engine.begin() as connection:
            for function in _FUNCTIONS:
                assert connection.scalar(select(func.to_regprocedure(function))) is None
        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
    finally:
        command.upgrade(config, "head")
