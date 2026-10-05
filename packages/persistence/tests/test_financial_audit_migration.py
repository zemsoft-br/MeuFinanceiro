from __future__ import annotations

from alembic import command
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import Engine

from meufinanceiro_persistence.migrations import build_alembic_config, current_revision

_REVISION = "0018_financial_audit_trail"
_PREVIOUS = "0017_movement_allocations"
_TABLE = "finance.audit_events"
_FUNCTION = (
    "finance.append_financial_audit_event(uuid,uuid,uuid,character varying,uuid,uuid)"
)


def _table_privilege(engine: Engine, role: str, privilege: str) -> bool:
    with engine.begin() as connection:
        value = connection.scalar(
            select(func.has_table_privilege(role, _TABLE, privilege))
        )
    return value is True


def _function_privilege(engine: Engine, role: str) -> bool:
    with engine.begin() as connection:
        value = connection.scalar(
            select(func.has_function_privilege(role, _FUNCTION, "EXECUTE"))
        )
    return value is True


def _rls_state(engine: Engine) -> tuple[bool, bool]:
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                SELECT c.relrowsecurity, c.relforcerowsecurity
                  FROM pg_catalog.pg_class c
                  JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'finance'
                   AND c.relname = 'audit_events'
                """
            )
        ).one()
    return bool(row[0]), bool(row[1])


def _function_security(engine: Engine) -> tuple[bool, tuple[str, ...]]:
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                SELECT p.prosecdef, COALESCE(p.proconfig, ARRAY[]::text[])
                  FROM pg_catalog.pg_proc p
                  JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
                 WHERE n.nspname = 'finance'
                   AND p.proname = 'append_financial_audit_event'
                   AND p.pronargs = 6
                """
            )
        ).one()
    return bool(row[0]), tuple(str(item) for item in row[1])


def _public_execute_grants(engine: Engine) -> int:
    with engine.begin() as connection:
        value = connection.scalar(
            text(
                """
                SELECT count(*)
                  FROM information_schema.routine_privileges
                 WHERE routine_schema = 'finance'
                   AND routine_name = 'append_financial_audit_event'
                   AND grantee = 'PUBLIC'
                   AND privilege_type = 'EXECUTE'
                """
            )
        )
    assert isinstance(value, int)
    return value


def test_financial_audit_foundation_downgrade_and_reupgrade(
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
            "audit_events",
            schema="finance",
        )

        command.upgrade(config, _REVISION)

        assert current_revision(engine) == _REVISION
        assert inspect(engine).has_table(
            "audit_events",
            schema="finance",
        )

        assert _rls_state(engine) == (True, False)

        assert _table_privilege(engine, app_database_user, "SELECT")
        assert not _table_privilege(engine, app_database_user, "INSERT")
        assert not _table_privilege(engine, app_database_user, "UPDATE")
        assert not _table_privilege(engine, app_database_user, "DELETE")

        assert _function_privilege(engine, app_database_user)
        assert _public_execute_grants(engine) == 0

        is_definer, function_config = _function_security(engine)

        assert is_definer is True
        assert "search_path=pg_catalog, pg_temp" in function_config

        columns = {
            column["name"]
            for column in inspect(engine).get_columns(
                "audit_events",
                schema="finance",
            )
        }

        assert columns == {
            "id",
            "installation_id",
            "residence_id",
            "actor_operator_id",
            "event_type",
            "subject_type",
            "subject_id",
            "related_subject_type",
            "related_subject_id",
            "event_schema_version",
            "occurred_at",
        }

        assert not columns.intersection(
            {
                "amount",
                "currency",
                "description",
                "reason",
                "payload",
                "raw_json",
                "request_digest",
                "before_snapshot",
                "after_snapshot",
            }
        )

        unique_constraints = {
            str(item["name"]): tuple(str(column) for column in item["column_names"])
            for item in inspect(engine).get_unique_constraints(
                "audit_events",
                schema="finance",
            )
            if item.get("name") is not None
        }

        assert unique_constraints == {
            "uq_finance_audit_events_event_subject": (
                "event_type",
                "subject_type",
                "subject_id",
            )
        }

        command.downgrade(config, _PREVIOUS)

        assert current_revision(engine) == _PREVIOUS
        assert not inspect(engine).has_table(
            "audit_events",
            schema="finance",
        )

        command.upgrade(config, _REVISION)

        assert current_revision(engine) == _REVISION
    finally:
        command.upgrade(config, "head")


_ENFORCEMENT_REVISION = "0019_financial_audit_enforcement"


def _audit_enforcement_trigger_rows(engine: Engine) -> list[tuple[str, bool, bool]]:
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                """
                SELECT tg.tgname, tg.tgdeferrable, tg.tginitdeferred
                  FROM pg_catalog.pg_trigger tg
                  JOIN pg_catalog.pg_class c ON c.oid = tg.tgrelid
                  JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'finance'
                   AND tg.tgname LIKE 'trg_finance_%_audit_required'
                   AND NOT tg.tgisinternal
                 ORDER BY tg.tgname
                """
            )
        ).all()
    return [(str(row[0]), bool(row[1]), bool(row[2])) for row in rows]


def test_financial_audit_enforcement_downgrade_preserves_foundation_rls(
    database_url: str,
    app_database_user: str,
    engine: Engine,
) -> None:
    config = build_alembic_config(
        database_url,
        app_database_user=app_database_user,
    )

    expected_triggers = {
        "trg_finance_accounts_audit_required",
        "trg_finance_categories_audit_required",
        "trg_finance_account_opening_balances_audit_required",
        "trg_finance_movements_audit_required",
        "trg_finance_transfers_audit_required",
        "trg_finance_movement_allocation_sets_audit_required",
    }

    try:
        command.downgrade(config, _ENFORCEMENT_REVISION)

        assert current_revision(engine) == _ENFORCEMENT_REVISION
        assert _rls_state(engine) == (True, False)

        trigger_rows = _audit_enforcement_trigger_rows(engine)

        assert {name for name, _, _ in trigger_rows} == expected_triggers
        assert all(
            is_deferrable and is_initially_deferred
            for _, is_deferrable, is_initially_deferred in trigger_rows
        )

        command.downgrade(config, _REVISION)

        assert current_revision(engine) == _REVISION
        assert _rls_state(engine) == (True, False)
        assert _audit_enforcement_trigger_rows(engine) == []

        command.upgrade(config, _ENFORCEMENT_REVISION)

        assert current_revision(engine) == _ENFORCEMENT_REVISION
        assert _rls_state(engine) == (True, False)
    finally:
        command.upgrade(config, "head")


_BANKING_BRIDGE_REVISION = "0020_banking_review_audit_bridge"


def _all_financial_audit_trigger_names(engine: Engine) -> set[str]:
    from sqlalchemy import text

    with engine.begin() as connection:
        rows = connection.execute(
            text(
                """
                SELECT tg.tgname
                  FROM pg_catalog.pg_trigger tg
                  JOIN pg_catalog.pg_class c ON c.oid = tg.tgrelid
                  JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                 WHERE NOT tg.tgisinternal
                   AND (
                        (n.nspname = 'finance'
                         AND tg.tgname LIKE 'trg_finance_%_audit_required')
                        OR tg.tgname = 'trg_banking_ledger_import_audit'
                   )
                 ORDER BY tg.tgname
                """
            )
        ).all()
    return {str(row[0]) for row in rows}


def _banking_bridge_function_state(
    engine: Engine,
) -> tuple[bool, tuple[str, ...], int]:
    from sqlalchemy import text

    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    p.prosecdef,
                    COALESCE(p.proconfig, ARRAY[]::text[]),
                    (
                        SELECT count(*)
                          FROM information_schema.routine_privileges rp
                         WHERE rp.routine_schema = 'finance'
                           AND rp.routine_name =
                               'audit_banking_ledger_import'
                           AND rp.grantee = 'PUBLIC'
                           AND rp.privilege_type = 'EXECUTE'
                    )
                  FROM pg_catalog.pg_proc p
                  JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
                 WHERE n.nspname = 'finance'
                   AND p.proname = 'audit_banking_ledger_import'
                   AND p.pronargs = 0
                """
            )
        ).one()
    return (
        bool(row[0]),
        tuple(str(item) for item in row[1]),
        int(row[2]),
    )


def _banking_bridge_function_exists(engine: Engine) -> bool:
    from sqlalchemy import text

    with engine.begin() as connection:
        value = connection.scalar(
            text(
                """
                SELECT count(*)
                  FROM pg_catalog.pg_proc p
                  JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
                 WHERE n.nspname = 'finance'
                   AND p.proname = 'audit_banking_ledger_import'
                   AND p.pronargs = 0
                """
            )
        )
    return value == 1


def test_banking_audit_bridge_downgrade_and_reupgrade(
    database_url: str,
    app_database_user: str,
    engine: Engine,
) -> None:
    config = build_alembic_config(
        database_url,
        app_database_user=app_database_user,
    )

    financial_triggers = {
        "trg_finance_accounts_audit_required",
        "trg_finance_categories_audit_required",
        "trg_finance_account_opening_balances_audit_required",
        "trg_finance_movements_audit_required",
        "trg_finance_transfers_audit_required",
        "trg_finance_movement_allocation_sets_audit_required",
    }
    banking_trigger = "trg_banking_ledger_import_audit"

    try:
        # Later migrations may already be applied: step back to the bridge first.
        command.downgrade(config, _BANKING_BRIDGE_REVISION)

        assert current_revision(engine) == _BANKING_BRIDGE_REVISION
        assert _rls_state(engine) == (True, False)
        assert _all_financial_audit_trigger_names(engine) == {
            *financial_triggers,
            banking_trigger,
        }

        security_definer, function_config, public_execute = (
            _banking_bridge_function_state(engine)
        )
        assert security_definer is False
        assert "search_path=pg_catalog, pg_temp" in function_config
        assert public_execute == 0

        command.downgrade(config, _ENFORCEMENT_REVISION)

        assert current_revision(engine) == _ENFORCEMENT_REVISION
        assert _rls_state(engine) == (True, False)
        assert _all_financial_audit_trigger_names(engine) == financial_triggers
        assert not _banking_bridge_function_exists(engine)
        assert len(_audit_enforcement_trigger_rows(engine)) == 6

        command.upgrade(config, _BANKING_BRIDGE_REVISION)

        assert current_revision(engine) == _BANKING_BRIDGE_REVISION
        assert _rls_state(engine) == (True, False)
        assert _all_financial_audit_trigger_names(engine) == {
            *financial_triggers,
            banking_trigger,
        }
    finally:
        command.upgrade(config, "head")
