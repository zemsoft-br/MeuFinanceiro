from __future__ import annotations

from alembic import command
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from meufinanceiro_persistence.migrations import build_alembic_config, current_revision

_REVISION = "0009_banking_sync_fairness"
_PREVIOUS = "0008_banking_tx_observations"


def test_sync_fairness_migration_downgrades_and_reupgrades(
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
        assert not inspect(engine).has_table("sync_cycles", schema="integrations")
        assert not inspect(engine).has_table(
            "sync_cycle_accounts",
            schema="integrations",
        )

        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
        assert inspect(engine).has_table("sync_cycles", schema="integrations")
        assert inspect(engine).has_table(
            "sync_cycle_accounts",
            schema="integrations",
        )

        command.downgrade(config, _PREVIOUS)
        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
    finally:
        command.upgrade(config, "head")
