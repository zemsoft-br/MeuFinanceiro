from __future__ import annotations

from alembic import command
from sqlalchemy import func, inspect, select
from sqlalchemy.engine import Engine

from meufinanceiro_persistence.migrations import build_alembic_config, current_revision

_REVISION = "0015_financial_transfers"
_PREVIOUS = "0014_financial_movements"
_TRANSFER_FUNCTION = "finance.validate_transfer_integrity()"


def _transfer_function_exists(engine: Engine) -> bool:
    with engine.begin() as connection:
        return (
            connection.scalar(select(func.to_regprocedure(_TRANSFER_FUNCTION)))
            is not None
        )


def test_financial_transfers_migration_downgrades_and_reupgrades(
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
        assert not inspect(engine).has_table("transfers", schema="finance")
        assert not inspect(engine).has_table("transfer_legs", schema="finance")
        assert not _transfer_function_exists(engine)

        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
        assert inspect(engine).has_table("transfers", schema="finance")
        assert inspect(engine).has_table("transfer_legs", schema="finance")
        assert _transfer_function_exists(engine)

        command.downgrade(config, _PREVIOUS)
        assert not _transfer_function_exists(engine)
        assert not inspect(engine).has_table("transfer_legs", schema="finance")
        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
        assert _transfer_function_exists(engine)
    finally:
        command.upgrade(config, "head")
