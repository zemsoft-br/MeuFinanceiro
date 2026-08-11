"""SQLAlchemy metadata for immutable financial-account opening balances."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from meufinanceiro_persistence.financial_account_schema import financial_accounts
from meufinanceiro_persistence.schema import metadata

# Migration 0013 adds the matching candidate key to PostgreSQL. Register it in
# metadata so the composite FK contract is explicit for tests and tooling.
UniqueConstraint(
    financial_accounts.c.id,
    financial_accounts.c.installation_id,
    financial_accounts.c.residence_id,
    financial_accounts.c.currency,
    name="uq_finance_accounts_opening_scope",
)

financial_opening_balances = Table(
    "account_opening_balances",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("account_id", UUID(as_uuid=True), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("amount", Numeric(24, 8), nullable=False),
    Column("effective_date", Date(), nullable=False),
    Column("created_by_operator_id", UUID(as_uuid=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "id::text ~ "
        "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
        name="ck_finance_opening_balance_id_uuid4",
    ),
    CheckConstraint(
        "currency ~ '^[A-Z]{3}$'",
        name="ck_finance_opening_balance_currency",
    ),
    CheckConstraint(
        "amount::text NOT IN ('NaN', 'Infinity', '-Infinity')",
        name="ck_finance_opening_balance_amount_finite",
    ),
    ForeignKeyConstraint(
        ["account_id", "installation_id", "residence_id", "currency"],
        [
            "finance.accounts.id",
            "finance.accounts.installation_id",
            "finance.accounts.residence_id",
            "finance.accounts.currency",
        ],
        ondelete="RESTRICT",
        name="fk_finance_opening_balance_account_scope",
    ),
    ForeignKeyConstraint(
        ["residence_id", "created_by_operator_id"],
        ["household.memberships.residence_id", "household.memberships.operator_id"],
        ondelete="RESTRICT",
        name="fk_finance_opening_balance_creator_membership",
    ),
    UniqueConstraint(
        "account_id",
        name="uq_finance_opening_balance_account",
    ),
    schema="finance",
)

Index(
    "ix_finance_opening_balance_residence_date",
    financial_opening_balances.c.residence_id,
    financial_opening_balances.c.effective_date,
    financial_opening_balances.c.account_id,
)

__all__ = ["financial_opening_balances"]
