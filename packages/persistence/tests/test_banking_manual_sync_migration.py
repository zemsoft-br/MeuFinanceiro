from __future__ import annotations

from alembic import command
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from meufinanceiro_persistence.migrations import (
    build_alembic_config,
    current_revision,
)

_REVISION = "0007_banking_manual_sync"


def test_manual_sync_migration_downgrades_and_reupgrades(
    database_url: str,
    app_database_user: str,
    engine: Engine,
) -> None:
    config = build_alembic_config(
        database_url,
        app_database_user=app_database_user,
    )

    try:
        command.downgrade(config, "0006_banking_residence_fk")
        assert current_revision(engine) == "0006_banking_residence_fk"
        inspector = inspect(engine)
        for table in ("sync_runs", "external_accounts", "sync_cursors"):
            assert not inspector.has_table(table, schema="integrations")

        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
        inspector = inspect(engine)
        for table in ("sync_runs", "external_accounts", "sync_cursors"):
            assert inspector.has_table(table, schema="integrations")

        command.downgrade(config, "0006_banking_residence_fk")
        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
    finally:
        command.upgrade(config, "head")
