from __future__ import annotations

from alembic import command
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from meufinanceiro_persistence.migrations import build_alembic_config, current_revision

_REVISION = "0010_banking_tx_reconciliation"
_PREVIOUS = "0009_banking_sync_fairness"


def test_transaction_reconciliation_migration_downgrades_and_reupgrades(
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
        inspector = inspect(engine)
        assert not inspector.has_table(
            "reconciled_transactions",
            schema="integrations",
        )
        assert not inspector.has_table(
            "reconciled_transaction_sources",
            schema="integrations",
        )

        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
        inspector = inspect(engine)
        assert inspector.has_table(
            "reconciled_transactions",
            schema="integrations",
        )
        assert inspector.has_table(
            "reconciled_transaction_sources",
            schema="integrations",
        )

        command.downgrade(config, _PREVIOUS)
        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
    finally:
        command.upgrade(config, "head")
