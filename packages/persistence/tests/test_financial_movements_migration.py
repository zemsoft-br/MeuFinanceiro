from __future__ import annotations

from alembic import command
from sqlalchemy import func, inspect, select
from sqlalchemy.engine import Engine

from meufinanceiro_persistence.migrations import build_alembic_config, current_revision

_REVISION = "0014_financial_movements"
_PREVIOUS = "0013_opening_balances"
_LOCK_FUNCTION = (
    "finance.lock_standard_movement_for_reversal(uuid, uuid, uuid, uuid)"
)


def _lock_function_exists(engine: Engine) -> bool:
    with engine.begin() as connection:
        return connection.scalar(select(func.to_regprocedure(_LOCK_FUNCTION))) is not None


def test_financial_movements_migration_downgrades_and_reupgrades(
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
        assert not inspect(engine).has_table("movements", schema="finance")
        assert not _lock_function_exists(engine)

        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
        assert inspect(engine).has_table("movements", schema="finance")
        assert _lock_function_exists(engine)

        command.downgrade(config, _PREVIOUS)
        assert not _lock_function_exists(engine)
        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
        assert _lock_function_exists(engine)
    finally:
        command.upgrade(config, "head")
