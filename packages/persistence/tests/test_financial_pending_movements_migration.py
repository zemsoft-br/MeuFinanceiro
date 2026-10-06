from __future__ import annotations

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from meufinanceiro_persistence.migrations import build_alembic_config, current_revision

_REVISION = "0022_pending_movement_indexes"
_PREVIOUS = "0021_categorization_rules"
_INDEXES = {
    "ix_finance_movements_pending_scan",
    "ix_finance_movements_pending_account_scan",
}


def _index_names(engine: Engine) -> set[str]:
    return {
        index["name"]
        for index in inspect(engine).get_indexes("movements", schema="finance")
    }


def test_revision_is_the_single_head_after_categorization_rules() -> None:
    assert len(_REVISION) <= 32
    config = build_alembic_config(
        "postgresql+psycopg://unused:unused@localhost/unused",
        app_database_user="unused_role",
    )
    directory = ScriptDirectory.from_config(config)
    assert directory.get_heads() == [_REVISION]
    script = directory.get_revision(_REVISION)
    assert script is not None and script.down_revision == _PREVIOUS


def test_pending_indexes_are_performance_only_and_reversible(
    database_url: str, app_database_user: str, engine: Engine
) -> None:
    config = build_alembic_config(database_url, app_database_user=app_database_user)
    try:
        command.downgrade(config, _PREVIOUS)
        assert current_revision(engine) == _PREVIOUS
        assert not _INDEXES & _index_names(engine)
        tables_before = set(inspect(engine).get_table_names(schema="finance"))
        columns_before = {
            column["name"]
            for column in inspect(engine).get_columns("movements", schema="finance")
        }

        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
        assert _INDEXES <= _index_names(engine)

        # Performance only: no table or column appears (no pending state).
        assert set(inspect(engine).get_table_names(schema="finance")) == tables_before
        assert {
            column["name"]
            for column in inspect(engine).get_columns("movements", schema="finance")
        } == columns_before

        indexes = {
            index["name"]: index
            for index in inspect(engine).get_indexes("movements", schema="finance")
        }
        for name in _INDEXES:
            predicate = indexes[name]["dialect_options"]["postgresql_where"]
            assert "STANDARD" in predicate and "INCOME" in predicate

        command.downgrade(config, _PREVIOUS)
        assert not _INDEXES & _index_names(engine)
        command.upgrade(config, _REVISION)
        assert _INDEXES <= _index_names(engine)
    finally:
        command.upgrade(config, "head")
