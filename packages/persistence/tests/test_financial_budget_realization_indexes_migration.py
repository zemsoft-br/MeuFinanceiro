from __future__ import annotations

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from meufinanceiro_persistence.migrations import build_alembic_config, current_revision

_REVISION = "0024_budget_realization_indexes"
_PREVIOUS = "0023_monthly_budgets"
_INDEX = "ix_finance_allocations_movement"


def _index_names(engine: Engine) -> set[str]:
    return {
        index["name"]
        for index in inspect(engine).get_indexes(
            "movement_allocations", schema="finance"
        )
    }


def test_revision_stays_in_the_single_history_after_monthly_budgets() -> None:
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


def test_index_is_performance_only_and_reversible(
    database_url: str, app_database_user: str, engine: Engine
) -> None:
    config = build_alembic_config(database_url, app_database_user=app_database_user)
    try:
        command.downgrade(config, _PREVIOUS)
        assert current_revision(engine) == _PREVIOUS
        assert _INDEX not in _index_names(engine)
        tables_before = set(inspect(engine).get_table_names(schema="finance"))
        columns_before = {
            column["name"]
            for column in inspect(engine).get_columns(
                "movement_allocations", schema="finance"
            )
        }

        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
        assert _INDEX in _index_names(engine)

        # No table, column or state appears: realized stays derived at read time.
        assert set(inspect(engine).get_table_names(schema="finance")) == tables_before
        assert {
            column["name"]
            for column in inspect(engine).get_columns(
                "movement_allocations", schema="finance"
            )
        } == columns_before
        index = next(
            item
            for item in inspect(engine).get_indexes(
                "movement_allocations", schema="finance"
            )
            if item["name"] == _INDEX
        )
        assert index["column_names"] == ["residence_id", "movement_id"]

        command.downgrade(config, _PREVIOUS)
        assert _INDEX not in _index_names(engine)
        command.upgrade(config, _REVISION)
        assert _INDEX in _index_names(engine)
    finally:
        command.upgrade(config, "head")
