# mypy: ignore-errors
"""Create canonical financial accounts with operator-aware RLS.

Revision ID: 0011_financial_accounts
Revises: 0010_banking_tx_reconciliation
Create Date: 2026-08-11
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0011_financial_accounts"
down_revision: str | None = "0010_banking_tx_reconciliation"
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
    op.execute("CREATE SCHEMA finance")

    op.execute(
        """
        CREATE TABLE finance.accounts (
            id uuid PRIMARY KEY,
            installation_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            owner_operator_id uuid NOT NULL,
            visibility_scope varchar(16) NOT NULL,
            account_type varchar(24) NOT NULL,
            custom_type_name varchar(96),
            name varchar(96) NOT NULL,
            currency varchar(3) NOT NULL,
            status varchar(16) NOT NULL,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            archived_at timestamptz,
            CONSTRAINT ck_finance_accounts_id_uuid4 CHECK (
                id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ),
            CONSTRAINT ck_finance_accounts_visibility CHECK (
                visibility_scope IN ('PERSONAL', 'SHARED', 'HOUSEHOLD')
            ),
            CONSTRAINT ck_finance_accounts_type CHECK (
                account_type IN (
                    'CHECKING', 'SAVINGS', 'CASH', 'DIGITAL_WALLET',
                    'INVESTMENT', 'BENEFIT', 'CUSTOM'
                )
            ),
            CONSTRAINT ck_finance_accounts_custom_type CHECK (
                (account_type = 'CUSTOM' AND custom_type_name IS NOT NULL
                    AND length(btrim(custom_type_name)) BETWEEN 1 AND 96)
                OR
                (account_type <> 'CUSTOM' AND custom_type_name IS NULL)
            ),
            CONSTRAINT ck_finance_accounts_name CHECK (
                length(btrim(name)) BETWEEN 1 AND 96
            ),
            CONSTRAINT ck_finance_accounts_currency CHECK (
                currency ~ '^[A-Z]{3}$'
            ),
            CONSTRAINT ck_finance_accounts_status CHECK (
                status IN ('ACTIVE', 'ARCHIVED')
            ),
            CONSTRAINT ck_finance_accounts_archive_state CHECK (
                (status = 'ACTIVE' AND archived_at IS NULL)
                OR
                (status = 'ARCHIVED' AND archived_at IS NOT NULL)
            ),
            CONSTRAINT ck_finance_accounts_timestamps CHECK (
                updated_at >= created_at
                AND (archived_at IS NULL OR archived_at >= created_at)
            ),
            CONSTRAINT fk_finance_accounts_residence FOREIGN KEY (
                residence_id, installation_id
            ) REFERENCES household.residences (
                id, installation_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_accounts_owner_membership FOREIGN KEY (
                residence_id, owner_operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT uq_finance_accounts_scope UNIQUE (
                id, installation_id, residence_id, owner_operator_id, visibility_scope
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_finance_accounts_residence_status "
        "ON finance.accounts (residence_id, status, created_at, id)"
    )
    op.execute(
        "CREATE INDEX ix_finance_accounts_owner "
        "ON finance.accounts (residence_id, owner_operator_id, status)"
    )

    op.execute(
        """
        CREATE TABLE finance.account_grants (
            id uuid PRIMARY KEY,
            installation_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            account_id uuid NOT NULL,
            owner_operator_id uuid NOT NULL,
            visibility_scope varchar(16) NOT NULL,
            operator_id uuid NOT NULL,
            created_at timestamptz NOT NULL,
            CONSTRAINT ck_finance_account_grants_shared CHECK (
                visibility_scope = 'SHARED'
            ),
            CONSTRAINT ck_finance_account_grants_not_owner CHECK (
                operator_id <> owner_operator_id
            ),
            CONSTRAINT fk_finance_account_grants_account_scope FOREIGN KEY (
                account_id, installation_id, residence_id,
                owner_operator_id, visibility_scope
            ) REFERENCES finance.accounts (
                id, installation_id, residence_id,
                owner_operator_id, visibility_scope
            ) ON DELETE CASCADE,
            CONSTRAINT fk_finance_account_grants_membership FOREIGN KEY (
                residence_id, operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT uq_finance_account_grants_account_operator UNIQUE (
                account_id, operator_id
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_finance_account_grants_operator "
        "ON finance.account_grants (residence_id, operator_id, account_id)"
    )
    op.execute(
        "CREATE INDEX ix_finance_account_grants_owner "
        "ON finance.account_grants (residence_id, owner_operator_id, account_id)"
    )

    residence = "NULLIF(current_setting('app.current_residence_id', true), '')::uuid"
    operator = "NULLIF(current_setting('app.current_operator_id', true), '')::uuid"
    grant_membership = (
        "EXISTS (SELECT 1 FROM household.memberships m "
        "WHERE m.residence_id = account_grants.residence_id "
        f"AND m.operator_id = {operator} AND m.status = 'active')"
    )
    account_membership = (
        "EXISTS (SELECT 1 FROM household.memberships m "
        "WHERE m.residence_id = accounts.residence_id "
        f"AND m.operator_id = {operator} AND m.status = 'active')"
    )

    op.execute("ALTER TABLE finance.account_grants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finance.account_grants FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY finance_account_grants_select ON finance.account_grants "
        "FOR SELECT USING ("
        f"account_grants.residence_id = {residence} "
        f"AND {grant_membership} AND ("
        f"account_grants.operator_id = {operator} "
        f"OR account_grants.owner_operator_id = {operator}))"
    )

    op.execute("ALTER TABLE finance.accounts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finance.accounts FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY finance_accounts_select ON finance.accounts "
        "FOR SELECT USING ("
        f"accounts.residence_id = {residence} AND {account_membership} AND ("
        f"accounts.owner_operator_id = {operator} "
        "OR accounts.visibility_scope = 'HOUSEHOLD' "
        "OR (accounts.visibility_scope = 'SHARED' AND EXISTS ("
        "SELECT 1 FROM finance.account_grants g "
        "WHERE g.account_id = accounts.id "
        "AND g.residence_id = accounts.residence_id "
        "AND g.visibility_scope = accounts.visibility_scope "
        f"AND g.operator_id = {operator}))))"
    )
    op.execute(
        "CREATE POLICY finance_accounts_insert ON finance.accounts "
        "FOR INSERT WITH CHECK ("
        f"accounts.residence_id = {residence} "
        f"AND accounts.owner_operator_id = {operator} "
        "AND accounts.status = 'ACTIVE' "
        "AND accounts.archived_at IS NULL "
        f"AND {account_membership})"
    )

    op.execute(f"GRANT USAGE ON SCHEMA finance TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON finance.accounts TO {role}")
    op.execute(f"GRANT SELECT ON finance.account_grants TO {role}")


def downgrade() -> None:
    role = _quoted_role()
    op.execute(f"REVOKE SELECT ON finance.account_grants FROM {role}")
    op.execute(f"REVOKE SELECT, INSERT ON finance.accounts FROM {role}")
    op.execute(f"REVOKE USAGE ON SCHEMA finance FROM {role}")
    op.execute("DROP TABLE finance.account_grants")
    op.execute("DROP TABLE finance.accounts")
    op.execute("DROP SCHEMA finance")
