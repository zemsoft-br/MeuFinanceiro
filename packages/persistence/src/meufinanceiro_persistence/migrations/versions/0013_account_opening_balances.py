# mypy: ignore-errors
"""Create immutable opening-balance anchors for financial accounts.

Revision ID: 0013_opening_balances
Revises: 0012_financial_categories
Create Date: 2026-08-11
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0013_opening_balances"
down_revision: str | None = "0012_financial_categories"
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
        "ALTER TABLE finance.accounts "
        "ADD CONSTRAINT uq_finance_accounts_opening_scope "
        "UNIQUE (id, installation_id, residence_id, currency)"
    )

    op.execute(
        """
        CREATE TABLE finance.account_opening_balances (
            id uuid PRIMARY KEY,
            installation_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            account_id uuid NOT NULL,
            currency varchar(3) NOT NULL,
            amount numeric(24,8) NOT NULL,
            effective_date date NOT NULL,
            created_by_operator_id uuid NOT NULL,
            created_at timestamptz NOT NULL,
            CONSTRAINT ck_finance_opening_balance_id_uuid4 CHECK (
                id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ),
            CONSTRAINT ck_finance_opening_balance_currency CHECK (
                currency ~ '^[A-Z]{3}$'
            ),
            CONSTRAINT ck_finance_opening_balance_amount_finite CHECK (
                amount::text NOT IN ('NaN', 'Infinity', '-Infinity')
            ),
            CONSTRAINT fk_finance_opening_balance_account_scope FOREIGN KEY (
                account_id, installation_id, residence_id, currency
            ) REFERENCES finance.accounts (
                id, installation_id, residence_id, currency
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_opening_balance_creator_membership FOREIGN KEY (
                residence_id, created_by_operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT uq_finance_opening_balance_account UNIQUE (account_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_finance_opening_balance_residence_date "
        "ON finance.account_opening_balances (residence_id, effective_date, account_id)"
    )

    residence = (
        "NULLIF(current_setting('app.current_residence_id', true), '')::uuid"
    )
    operator = (
        "NULLIF(current_setting('app.current_operator_id', true), '')::uuid"
    )
    active_membership = (
        "EXISTS (SELECT 1 FROM household.memberships m "
        "WHERE m.residence_id = account_opening_balances.residence_id "
        f"AND m.operator_id = {operator} AND m.status = 'active')"
    )
    visible_account = (
        "EXISTS (SELECT 1 FROM finance.accounts a "
        "WHERE a.id = account_opening_balances.account_id "
        "AND a.installation_id = account_opening_balances.installation_id "
        "AND a.residence_id = account_opening_balances.residence_id "
        "AND a.currency = account_opening_balances.currency)"
    )
    owned_active_account = (
        "EXISTS (SELECT 1 FROM finance.accounts a "
        "WHERE a.id = account_opening_balances.account_id "
        "AND a.installation_id = account_opening_balances.installation_id "
        "AND a.residence_id = account_opening_balances.residence_id "
        "AND a.currency = account_opening_balances.currency "
        f"AND a.owner_operator_id = {operator} AND a.status = 'ACTIVE')"
    )

    op.execute(
        "ALTER TABLE finance.account_opening_balances ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE finance.account_opening_balances FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY finance_opening_balances_select "
        "ON finance.account_opening_balances FOR SELECT USING ("
        f"account_opening_balances.residence_id = {residence} "
        f"AND {active_membership} AND {visible_account})"
    )
    op.execute(
        "CREATE POLICY finance_opening_balances_insert "
        "ON finance.account_opening_balances FOR INSERT WITH CHECK ("
        f"account_opening_balances.residence_id = {residence} "
        f"AND account_opening_balances.created_by_operator_id = {operator} "
        f"AND {active_membership} AND {owned_active_account})"
    )

    op.execute(
        f"GRANT SELECT, INSERT ON finance.account_opening_balances TO {role}"
    )


def downgrade() -> None:
    role = _quoted_role()
    op.execute(
        f"REVOKE SELECT, INSERT ON finance.account_opening_balances FROM {role}"
    )
    op.execute("DROP TABLE finance.account_opening_balances")
    op.execute(
        "ALTER TABLE finance.accounts "
        "DROP CONSTRAINT uq_finance_accounts_opening_scope"
    )
