# mypy: ignore-errors
"""Create canonical financial category trees with operator-aware RLS.

Revision ID: 0012_financial_categories
Revises: 0011_financial_accounts
Create Date: 2026-08-11
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0012_financial_categories"
down_revision: str | None = "0011_financial_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


def _quoted_role() -> str:
    role_name = context.config.get_main_option("app_database_user")
    if not _ROLE_PATTERN.fullmatch(role_name):
        raise RuntimeError("invalid app_database_user for migration grants")
    return f'"{role_name}"'


def upgrade() -> None:
    role = _quoted_role()

    op.execute(
        """
        CREATE TABLE finance.categories (
            id uuid PRIMARY KEY,
            installation_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            owner_operator_id uuid NOT NULL,
            visibility_scope varchar(16) NOT NULL,
            parent_id uuid,
            name varchar(96) NOT NULL,
            status varchar(16) NOT NULL,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            disabled_at timestamptz,
            CONSTRAINT ck_finance_categories_id_uuid4 CHECK (
                id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ),
            CONSTRAINT ck_finance_categories_visibility CHECK (
                visibility_scope IN ('PERSONAL', 'HOUSEHOLD')
            ),
            CONSTRAINT ck_finance_categories_name CHECK (
                length(btrim(name)) BETWEEN 1 AND 96
            ),
            CONSTRAINT ck_finance_categories_status CHECK (
                status IN ('ACTIVE', 'DISABLED')
            ),
            CONSTRAINT ck_finance_categories_disable_state CHECK (
                (status = 'ACTIVE' AND disabled_at IS NULL)
                OR
                (status = 'DISABLED' AND disabled_at IS NOT NULL)
            ),
            CONSTRAINT ck_finance_categories_timestamps CHECK (
                updated_at >= created_at
                AND (disabled_at IS NULL OR disabled_at >= created_at)
            ),
            CONSTRAINT ck_finance_categories_not_self_parent CHECK (
                parent_id IS NULL OR parent_id <> id
            ),
            CONSTRAINT fk_finance_categories_residence FOREIGN KEY (
                residence_id, installation_id
            ) REFERENCES household.residences (
                id, installation_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_categories_owner_membership FOREIGN KEY (
                residence_id, owner_operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT uq_finance_categories_scope UNIQUE (
                id, installation_id, residence_id, owner_operator_id, visibility_scope
            ),
            CONSTRAINT fk_finance_categories_parent_scope FOREIGN KEY (
                parent_id, installation_id, residence_id,
                owner_operator_id, visibility_scope
            ) REFERENCES finance.categories (
                id, installation_id, residence_id,
                owner_operator_id, visibility_scope
            ) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_finance_categories_residence_status "
        "ON finance.categories (residence_id, status, name, id)"
    )
    op.execute(
        "CREATE INDEX ix_finance_categories_parent "
        "ON finance.categories (residence_id, parent_id, name, id)"
    )
    op.execute(
        "CREATE INDEX ix_finance_categories_owner "
        "ON finance.categories (residence_id, owner_operator_id, status)"
    )

    residence = (
        "NULLIF(current_setting('app.current_residence_id', true), '')::uuid"
    )
    operator = (
        "NULLIF(current_setting('app.current_operator_id', true), '')::uuid"
    )
    active_membership = (
        "EXISTS (SELECT 1 FROM household.memberships m "
        "WHERE m.residence_id = categories.residence_id "
        f"AND m.operator_id = {operator} AND m.status = 'active')"
    )

    op.execute("ALTER TABLE finance.categories ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finance.categories FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY finance_categories_select ON finance.categories "
        "FOR SELECT USING ("
        f"categories.residence_id = {residence} "
        f"AND {active_membership} AND ("
        f"categories.owner_operator_id = {operator} "
        "OR categories.visibility_scope = 'HOUSEHOLD'))"
    )
    op.execute(
        "CREATE POLICY finance_categories_insert ON finance.categories "
        "FOR INSERT WITH CHECK ("
        f"categories.residence_id = {residence} "
        f"AND categories.owner_operator_id = {operator} "
        "AND categories.visibility_scope IN ('PERSONAL', 'HOUSEHOLD') "
        "AND categories.status = 'ACTIVE' "
        "AND categories.disabled_at IS NULL "
        f"AND {active_membership})"
    )

    op.execute(f"GRANT SELECT, INSERT ON finance.categories TO {role}")


def downgrade() -> None:
    role = _quoted_role()
    op.execute(f"REVOKE SELECT, INSERT ON finance.categories FROM {role}")
    op.execute("DROP TABLE finance.categories")
