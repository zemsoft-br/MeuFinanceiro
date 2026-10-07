"""Migration proofs for the recurrence suggestion decisions (0027)."""

from __future__ import annotations

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import func, inspect, select
from sqlalchemy.engine import Engine

from meufinanceiro_persistence.migrations import build_alembic_config, current_revision

_REVISION = "0027_recurrence_suggestions"
_PREVIOUS = "0026_recurrence_revisions"
_TABLE = "finance.recurrence_suggestion_decisions"
_FUNCTIONS = (
    "finance.validate_recurrence_suggestion_decision()",
    "finance.reject_recurrence_suggestion_decision_update()",
)
_INDEX = "ix_finance_movements_expense_scan"


def _privilege(engine: Engine, role: str, privilege: str) -> bool:
    with engine.begin() as connection:
        return (
            connection.scalar(select(func.has_table_privilege(role, _TABLE, privilege)))
            is True
        )


def _has_index(engine: Engine, name: str) -> bool:
    return any(
        index["name"] == name
        for index in inspect(engine).get_indexes("movements", schema="finance")
    )


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


def test_decision_table_rls_grants_triggers_and_symmetric_downgrade(
    database_url: str, app_database_user: str, engine: Engine
) -> None:
    config = build_alembic_config(database_url, app_database_user=app_database_user)
    try:
        command.downgrade(config, _PREVIOUS)
        assert current_revision(engine) == _PREVIOUS
        assert not inspect(engine).has_table(
            "recurrence_suggestion_decisions", schema="finance"
        )
        assert not _has_index(engine, _INDEX)
        with engine.begin() as connection:
            for function in _FUNCTIONS:
                assert connection.scalar(select(func.to_regprocedure(function))) is None

        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
        assert inspect(engine).has_table(
            "recurrence_suggestion_decisions", schema="finance"
        )
        assert _has_index(engine, _INDEX)

        with engine.begin() as connection:
            state = connection.exec_driver_sql(
                "SELECT c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
                "ON n.oid = c.relnamespace WHERE n.nspname = 'finance' "
                "AND c.relname = 'recurrence_suggestion_decisions'"
            ).one()
            assert (bool(state[0]), bool(state[1])) == (True, True)
            policies = dict(
                connection.exec_driver_sql(
                    "SELECT policyname, cmd FROM pg_policies "
                    "WHERE schemaname = 'finance' "
                    "AND tablename = 'recurrence_suggestion_decisions'"
                ).all()
            )
            assert policies == {
                "finance_recurrence_decisions_select": "SELECT",
                "finance_recurrence_decisions_insert": "INSERT",
            }
            triggers = {
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal "
                    "AND tgrelid = 'finance.recurrence_suggestion_decisions'::regclass"
                ).all()
            }
            assert triggers == {
                "trg_finance_validate_recurrence_suggestion_decision",
                "trg_finance_reject_recurrence_suggestion_decision_update",
            }
            uniques = {
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT conname FROM pg_constraint WHERE contype = 'u' "
                    "AND conrelid = 'finance.recurrence_suggestion_decisions'::regclass"
                ).all()
            }
            assert uniques == {
                "uq_finance_recurrence_decisions_operator_fingerprint",
                "uq_finance_recurrence_decisions_recurrence",
            }

        assert _privilege(engine, app_database_user, "SELECT")
        assert _privilege(engine, app_database_user, "INSERT")
        for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
            assert not _privilege(engine, app_database_user, privilege)

        command.downgrade(config, _PREVIOUS)
        assert not inspect(engine).has_table(
            "recurrence_suggestion_decisions", schema="finance"
        )
        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
    finally:
        command.upgrade(config, "head")
