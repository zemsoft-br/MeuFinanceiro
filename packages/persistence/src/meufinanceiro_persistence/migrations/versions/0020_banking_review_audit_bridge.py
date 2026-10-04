# mypy: ignore-errors
"""Bridge explicit banking imports into the financial audit trail.

Revision ID: 0020_banking_review_audit_bridge
Revises: 0019_financial_audit_enforcement
Create Date: 2026-08-18
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0020_banking_review_audit_bridge"
down_revision: str | None = "0019_financial_audit_enforcement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


def _runtime_role_literal() -> str:
    role_name = context.config.get_main_option("app_database_user")
    if not _ROLE_PATTERN.fullmatch(role_name):
        raise RuntimeError("invalid app_database_user for banking audit bridge")
    return f"'{role_name}'"


def upgrade() -> None:
    runtime_role = _runtime_role_literal()
    op.execute(
        f"""
        CREATE FUNCTION finance.audit_banking_ledger_import()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
            IF SESSION_USER <> {runtime_role} THEN
                RETURN NEW;
            END IF;

            IF NEW.decision IN ('IMPORT_AS_INCOME', 'IMPORT_AS_EXPENSE') THEN
                IF NEW.movement_id IS NULL THEN
                    RAISE EXCEPTION 'banking ledger import is missing Movement'
                        USING ERRCODE = '23514';
                END IF;
                PERFORM finance.append_financial_audit_event(
                    NEW.installation_id,
                    NEW.residence_id,
                    NEW.decided_by_operator_id,
                    'MOVEMENT_CREATED',
                    NEW.movement_id,
                    NULL
                );
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_banking_ledger_import_audit "
        "AFTER INSERT ON integrations.reconciled_transaction_ledger_links "
        "FOR EACH ROW EXECUTE FUNCTION finance.audit_banking_ledger_import()"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION finance.audit_banking_ledger_import() FROM PUBLIC"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_banking_ledger_import_audit "
        "ON integrations.reconciled_transaction_ledger_links"
    )
    op.execute("DROP FUNCTION IF EXISTS finance.audit_banking_ledger_import()")
