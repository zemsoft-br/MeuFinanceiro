from __future__ import annotations

from alembic import command
from sqlalchemy import func, inspect, select
from sqlalchemy.engine import Engine

from meufinanceiro_persistence.migrations import build_alembic_config, current_revision

_REVISION = "0016_banking_ledger_review"
_PREVIOUS = "0015_financial_transfers"
_TABLE = "integrations.reconciled_transaction_ledger_links"


def _table_privilege(engine: Engine, role: str, privilege: str) -> bool:
    with engine.begin() as connection:
        value = connection.scalar(
            select(func.has_table_privilege(role, _TABLE, privilege))
        )
    return value is True


def _rls_state(engine: Engine) -> tuple[bool, bool]:
    with engine.begin() as connection:
        state = connection.exec_driver_sql(
            """
            SELECT c.relrowsecurity, c.relforcerowsecurity
              FROM pg_catalog.pg_class c
              JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'integrations'
               AND c.relname = 'reconciled_transaction_ledger_links'
            """
        ).one()
    return bool(state[0]), bool(state[1])


def test_banking_ledger_review_migration_downgrades_and_reupgrades(
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
            "reconciled_transaction_ledger_links",
            schema="integrations",
        )

        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
        assert inspect(engine).has_table(
            "reconciled_transaction_ledger_links",
            schema="integrations",
        )
        assert _rls_state(engine) == (True, True)
        assert _table_privilege(engine, app_database_user, "SELECT")
        assert _table_privilege(engine, app_database_user, "INSERT")
        assert not _table_privilege(engine, app_database_user, "UPDATE")
        assert not _table_privilege(engine, app_database_user, "DELETE")

        command.downgrade(config, _PREVIOUS)
        assert not inspect(engine).has_table(
            "reconciled_transaction_ledger_links",
            schema="integrations",
        )
        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
    finally:
        command.upgrade(config, "head")
