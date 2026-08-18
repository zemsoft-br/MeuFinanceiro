from __future__ import annotations

from alembic import command
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import Engine

from meufinanceiro_persistence.migrations import build_alembic_config, current_revision

_REVISION = "0020_banking_review_audit_bridge"
_PREVIOUS = "0017_movement_allocations"
_TABLE = "finance.audit_events"
_FUNCTION = (
    "finance.append_financial_audit_event("
    "uuid,uuid,uuid,character varying,uuid,uuid)"
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


def _function_security(
    engine: Engine,
    *,
    function_name: str,
    argument_count: int,
) -> tuple[bool, tuple[str, ...]]:
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                SELECT p.prosecdef, COALESCE(p.proconfig, ARRAY[]::text[])
                  FROM pg_catalog.pg_proc p
                  JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
                 WHERE n.nspname = 'finance'
                   AND p.proname = :function_name
                   AND p.pronargs = :argument_count
                """
            ),
            {
                "function_name": function_name,
                "argument_count": argument_count,
            },
        ).one()
    return bool(row[0]), tuple(str(item) for item in row[1])


def _public_execute_grants(engine: Engine, routine_name: str) -> int:
    with engine.begin() as connection:
        value = connection.scalar(
            text(
                """
                SELECT count(*)
                  FROM information_schema.routine_privileges
                 WHERE routine_schema = 'finance'
                   AND routine_name = :routine_name
                   AND grantee = 'PUBLIC'
                   AND privilege_type = 'EXECUTE'
                """
            ),
            {"routine_name": routine_name},
        )
    assert isinstance(value, int)
    return value


def _audit_trigger_names(engine: Engine) -> set[str]:
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                """
                SELECT t.tgname
                  FROM pg_catalog.pg_trigger t
                  JOIN pg_catalog.pg_class c ON c.oid = t.tgrelid
                  JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                 WHERE NOT t.tgisinternal
                   AND (
                        (n.nspname = 'finance'
                         AND t.tgname LIKE 'trg_finance_%_audit_required')
                        OR t.tgname = 'trg_banking_ledger_import_audit'
                   )
                """
            )
        ).all()
    return {str(row[0]) for row in rows}


def _audit_unique_constraints(engine: Engine) -> dict[str, tuple[str, ...]]:
    constraints = inspect(engine).get_unique_constraints(
        "audit_events",
        schema="finance",
    )
    return {
        str(item["name"]): tuple(str(column) for column in item["column_names"])
        for item in constraints
        if item.get("name") is not None
    }


def test_financial_audit_migrations_downgrade_and_reupgrade(
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
        assert not inspect(engine).has_table("audit_events", schema="finance")

        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
        assert inspect(engine).has_table("audit_events", schema="finance")

        # RLS remains active for runtime reads. FORCE is deliberately disabled
        # because the SECURITY DEFINER writer relies on table-owner bypass;
        # runtime still has no direct write privilege.
        assert _rls_state(engine) == (True, False)
        assert _table_privilege(engine, app_database_user, "SELECT")
        assert not _table_privilege(engine, app_database_user, "INSERT")
        assert not _table_privilege(engine, app_database_user, "UPDATE")
        assert not _table_privilege(engine, app_database_user, "DELETE")
        assert _function_privilege(engine, app_database_user)

        for routine_name in (
            "append_financial_audit_event",
            "require_financial_audit_event",
            "audit_banking_ledger_import",
        ):
            assert _public_execute_grants(engine, routine_name) == 0

        append_definer, append_config = _function_security(
            engine,
            function_name="append_financial_audit_event",
            argument_count=6,
        )
        assert append_definer is True
        assert "search_path=pg_catalog, pg_temp" in append_config

        enforcement_definer, enforcement_config = _function_security(
            engine,
            function_name="require_financial_audit_event",
            argument_count=0,
        )
        assert enforcement_definer is False
        assert "search_path=pg_catalog, pg_temp" in enforcement_config

        banking_definer, banking_config = _function_security(
            engine,
            function_name="audit_banking_ledger_import",
            argument_count=0,
        )
        assert banking_definer is False
        assert "search_path=pg_catalog, pg_temp" in banking_config

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
        assert _audit_unique_constraints(engine) == {
            "uq_finance_audit_events_event_subject": (
                "event_type",
                "subject_type",
                "subject_id",
            )
        }

        assert _audit_trigger_names(engine) == {
            "trg_finance_accounts_audit_required",
            "trg_finance_categories_audit_required",
            "trg_finance_account_opening_balances_audit_required",
            "trg_finance_movements_audit_required",
            "trg_finance_transfers_audit_required",
            "trg_finance_movement_allocation_sets_audit_required",
            "trg_banking_ledger_import_audit",
        }

        command.downgrade(config, _PREVIOUS)
        assert not inspect(engine).has_table("audit_events", schema="finance")
        command.upgrade(config, _REVISION)
        assert current_revision(engine) == _REVISION
    finally:
        command.upgrade(config, "head")
