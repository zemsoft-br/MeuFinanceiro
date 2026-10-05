from __future__ import annotations

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import func, inspect, select
from sqlalchemy.engine import Engine

from meufinanceiro_persistence.migrations import build_alembic_config, current_revision

_REVISION = "0021_categorization_rules"
_PREVIOUS = "0020_banking_review_audit_bridge"
_RULES = "finance.categorization_rules"
_ORIGINS = "finance.movement_allocation_rule_origins"
_FUNCTIONS = (
    "finance.validate_categorization_rule_row()",
    "finance.enforce_categorization_rule_immutability()",
    "finance.validate_movement_allocation_rule_origin_row()",
)


def _privilege(engine: Engine, role: str, table: str, privilege: str) -> bool:
    with engine.begin() as connection:
        return (
            connection.scalar(select(func.has_table_privilege(role, table, privilege)))
            is True
        )


def _column_privilege(engine: Engine, role: str, column: str) -> bool:
    with engine.begin() as connection:
        return (
            connection.scalar(
                select(func.has_column_privilege(role, _RULES, column, "UPDATE"))
            )
            is True
        )


def _rls_state(engine: Engine, table: str) -> tuple[bool, bool]:
    schema, name = table.split(".", maxsplit=1)
    with engine.begin() as connection:
        state = connection.exec_driver_sql(
            """
            SELECT c.relrowsecurity, c.relforcerowsecurity
              FROM pg_catalog.pg_class c
              JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = %(schema)s AND c.relname = %(name)s
            """,
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


def _head(config: object) -> str:
    head = ScriptDirectory.from_config(config).get_current_head()  # type: ignore[arg-type]
    assert head is not None
    return head


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
    script = ScriptDirectory.from_config(config).get_revision(_REVISION)
    assert script is not None and script.down_revision == _PREVIOUS


def test_categorization_rules_downgrade_and_reupgrade(
    database_url: str,
    app_database_user: str,
    engine: Engine,
) -> None:
    config = build_alembic_config(database_url, app_database_user=app_database_user)

    try:
        command.downgrade(config, _PREVIOUS)
        assert current_revision(engine) == _PREVIOUS
        assert not inspect(engine).has_table("categorization_rules", schema="finance")
        assert not inspect(engine).has_table(
            "movement_allocation_rule_origins", schema="finance"
        )

        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION

        assert inspect(engine).has_table("categorization_rules", schema="finance")
        assert inspect(engine).has_table(
            "movement_allocation_rule_origins", schema="finance"
        )
        for table in (_RULES, _ORIGINS):
            assert _rls_state(engine, table) == (True, True)

        assert _policies(engine, _RULES) == {
            "finance_cat_rules_select": "SELECT",
            "finance_cat_rules_insert": "INSERT",
            "finance_cat_rules_update": "UPDATE",
        }
        assert _policies(engine, _ORIGINS) == {
            "finance_rule_origins_select": "SELECT",
            "finance_rule_origins_insert": "INSERT",
        }

        # Rules: semantic columns are never updatable; only the disable columns are.
        assert _privilege(engine, app_database_user, _RULES, "SELECT")
        assert _privilege(engine, app_database_user, _RULES, "INSERT")
        assert not _privilege(engine, app_database_user, _RULES, "DELETE")
        for column in (
            "description_pattern",
            "description_matcher",
            "priority",
            "target_category_id",
            "account_id",
            "result_effect",
            "created_by_operator_id",
        ):
            assert not _column_privilege(engine, app_database_user, column)
        for column in ("status", "disabled_at", "disabled_by_operator_id"):
            assert _column_privilege(engine, app_database_user, column)

        # Provenance: append-only.
        assert _privilege(engine, app_database_user, _ORIGINS, "SELECT")
        assert _privilege(engine, app_database_user, _ORIGINS, "INSERT")
        assert not _privilege(engine, app_database_user, _ORIGINS, "UPDATE")
        assert not _privilege(engine, app_database_user, _ORIGINS, "DELETE")

        with engine.begin() as connection:
            for function in _FUNCTIONS:
                assert connection.scalar(select(func.to_regprocedure(function)))

        origin_columns = {
            column["name"]
            for column in inspect(engine).get_columns(
                "movement_allocation_rule_origins", schema="finance"
            )
        }
        # No financial payload copy: only identity, scope and the rule reference.
        assert origin_columns == {
            "allocation_set_id",
            "installation_id",
            "residence_id",
            "movement_id",
            "rule_id",
            "created_at",
        }

        command.downgrade(config, _PREVIOUS)
        assert current_revision(engine) == _PREVIOUS
        with engine.begin() as connection:
            for function in _FUNCTIONS:
                assert connection.scalar(select(func.to_regprocedure(function))) is None
        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
    finally:
        command.upgrade(config, "head")
