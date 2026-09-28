from __future__ import annotations

from alembic import command
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from meufinanceiro_persistence.migrations import build_alembic_config, current_revision

_REVISION = "0013_opening_balances"
_PREVIOUS = "0012_financial_categories"


def test_opening_balance_migration_downgrades_and_reupgrades(
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
        assert not inspect(engine).has_table(
            "account_opening_balances",
            schema="finance",
        )

        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
        assert inspect(engine).has_table(
            "account_opening_balances",
            schema="finance",
        )

        command.downgrade(config, _PREVIOUS)
        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
    finally:
        command.upgrade(config, "head")
