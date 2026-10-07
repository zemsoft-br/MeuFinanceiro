"""Migration proofs for the recurrence revision history (0026)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from alembic import command
from alembic.script import ScriptDirectory
from meufinanceiro_finance import (
    FinancialRecurrenceDraft,
    FinancialRecurrenceReplacement,
    FinancialResultEffect,
    Money,
    new_financial_idempotency_key,
)
from sqlalchemy import func, inspect, select
from sqlalchemy.engine import Engine

from meufinanceiro_persistence.financial_recurrence_store import (
    FinancialRecurrenceStore,
)
from meufinanceiro_persistence.migrations import build_alembic_config, current_revision

if TYPE_CHECKING:
    from conftest import BudgetWorld

_REVISION = "0026_recurrence_revisions"
_PREVIOUS = "0025_monthly_recurrences"
_TABLE = "finance.recurrence_revisions"
_FUNCTIONS = (
    "finance.record_recurrence_revision()",
    "finance.validate_recurrence_revision_insert()",
    "finance.reject_recurrence_revision_update()",
)


def _privilege(engine: Engine, role: str, privilege: str) -> bool:
    with engine.begin() as connection:
        return (
            connection.scalar(select(func.has_table_privilege(role, _TABLE, privilege)))
            is True
        )


def test_revision_id_fits_and_history_has_a_single_head() -> None:
    assert len(_REVISION) <= 32
    config = build_alembic_config(
        "postgresql+psycopg://unused:unused@localhost/unused",
        app_database_user="unused_role",
    )
    directory = ScriptDirectory.from_config(config)
    heads = directory.get_heads()
    assert len(heads) == 1
    assert _REVISION in {
        item.revision for item in directory.walk_revisions(base="base", head=heads[0])
    }
    script = directory.get_revision(_REVISION)
    assert script is not None and script.down_revision == _PREVIOUS


def test_history_table_rls_grants_triggers_and_symmetric_downgrade(
    database_url: str, app_database_user: str, engine: Engine
) -> None:
    config = build_alembic_config(database_url, app_database_user=app_database_user)
    try:
        command.downgrade(config, _PREVIOUS)
        assert current_revision(engine) == _PREVIOUS
        assert not inspect(engine).has_table("recurrence_revisions", schema="finance")
        assert inspect(engine).has_table("recurrences", schema="finance")
        with engine.begin() as connection:
            for function in _FUNCTIONS:
                assert connection.scalar(select(func.to_regprocedure(function))) is None

        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
        assert inspect(engine).has_table("recurrence_revisions", schema="finance")

        with engine.begin() as connection:
            state = connection.exec_driver_sql(
                "SELECT c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
                "ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'finance' AND c.relname = 'recurrence_revisions'"
            ).one()
            assert (bool(state[0]), bool(state[1])) == (True, True)
            rules_state = connection.exec_driver_sql(
                "SELECT c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
                "ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'finance' AND c.relname = 'recurrences'"
            ).one()
            # The backfill lifts FORCE only around the copy and always restores it.
            assert (bool(rules_state[0]), bool(rules_state[1])) == (True, True)
            policies = dict(
                connection.exec_driver_sql(
                    "SELECT policyname, cmd FROM pg_policies "
                    "WHERE schemaname = 'finance' "
                    "AND tablename = 'recurrence_revisions'"
                ).all()
            )
            assert policies == {
                "finance_recurrence_revisions_select": "SELECT",
                "finance_recurrence_revisions_insert": "INSERT",
            }
            triggers = {
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal "
                    "AND tgrelid IN ('finance.recurrences'::regclass, "
                    "'finance.recurrence_revisions'::regclass)"
                ).all()
            }
            assert {
                "trg_finance_record_recurrence_revision",
                "trg_finance_validate_recurrence_revision_insert",
                "trg_finance_reject_recurrence_revision_update",
            } <= triggers

        assert _privilege(engine, app_database_user, "SELECT")
        assert _privilege(engine, app_database_user, "INSERT")
        for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
            assert not _privilege(engine, app_database_user, privilege)
        with engine.begin() as connection:
            for column in ("description", "version", "status", "recorded_at"):
                assert (
                    connection.scalar(
                        select(
                            func.has_column_privilege(
                                app_database_user, _TABLE, column, "UPDATE"
                            )
                        )
                    )
                    is False
                )

        command.downgrade(config, _PREVIOUS)
        assert not inspect(engine).has_table("recurrence_revisions", schema="finance")
        with engine.begin() as connection:
            for function in _FUNCTIONS:
                assert connection.scalar(select(func.to_regprocedure(function))) is None
        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
    finally:
        command.upgrade(config, "head")


def test_existing_rules_are_backfilled_with_their_current_revision_and_continue(
    database_url: str,
    app_database_user: str,
    engine: Engine,
    budget_world: BudgetWorld,
) -> None:
    config = build_alembic_config(database_url, app_database_user=app_database_user)
    store = FinancialRecurrenceStore(budget_world.runtime)
    try:
        command.downgrade(config, _PREVIOUS)
        rule = store.create_recurrence(
            **budget_world.scope(),
            idempotency_key=new_financial_idempotency_key(),
            draft=FinancialRecurrenceDraft(
                account_id=budget_world.account(),
                description="Internet",
                result_effect=FinancialResultEffect.EXPENSE,
                expected=Money(Decimal("120"), "BRL"),
                start_date=date(2026, 1, 10),
                day_of_month=10,
                end_date=None,
            ),
        )
        edited = store.replace_recurrence(
            **budget_world.scope(),
            recurrence_id=rule.id,
            replacement=FinancialRecurrenceReplacement(
                expected_version=1,
                description="Antes da migration",
                expected_amount=Decimal("130"),
                day_of_month=10,
                end_date=None,
            ),
            today=date(2026, 10, 6),
        ).recurrence
        assert edited.version == 2

        command.upgrade(config, "head")

        # Earlier states were never stored: the current one becomes the first record.
        history = store.list_recurrence_revisions(
            **budget_world.scope(), recurrence_id=rule.id
        )
        assert [(r.version, r.description) for r in history] == [
            (2, "Antes da migration")
        ]

        store.pause_recurrence(**budget_world.scope(), recurrence_id=rule.id)
        history = store.list_recurrence_revisions(
            **budget_world.scope(), recurrence_id=rule.id
        )
        assert [(r.version, r.status.value) for r in history] == [
            (2, "ACTIVE"),
            (3, "PAUSED"),
        ]
    finally:
        command.upgrade(config, "head")
