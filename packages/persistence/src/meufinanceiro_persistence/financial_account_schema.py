"""SQLAlchemy metadata for canonical financial accounts."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from meufinanceiro_persistence.schema import metadata

financial_accounts = Table(
    "accounts",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("owner_operator_id", UUID(as_uuid=True), nullable=False),
    Column("visibility_scope", String(16), nullable=False),
    Column("account_type", String(24), nullable=False),
    Column("custom_type_name", String(96), nullable=True),
    Column("name", String(96), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("archived_at", DateTime(timezone=True), nullable=True),
    CheckConstraint(
        "id::text ~ "
        "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
        name="ck_finance_accounts_id_uuid4",
    ),
    CheckConstraint(
        "visibility_scope IN ('PERSONAL', 'SHARED', 'HOUSEHOLD')",
        name="ck_finance_accounts_visibility",
    ),
    CheckConstraint(
        "account_type IN ('CHECKING', 'SAVINGS', 'CASH', 'DIGITAL_WALLET', "
        "'INVESTMENT', 'BENEFIT', 'CUSTOM')",
        name="ck_finance_accounts_type",
    ),
    CheckConstraint(
        "(account_type = 'CUSTOM' AND custom_type_name IS NOT NULL "
        "AND length(btrim(custom_type_name)) BETWEEN 1 AND 96) OR "
        "(account_type <> 'CUSTOM' AND custom_type_name IS NULL)",
        name="ck_finance_accounts_custom_type",
    ),
    CheckConstraint(
        "length(btrim(name)) BETWEEN 1 AND 96",
        name="ck_finance_accounts_name",
    ),
    CheckConstraint(
        "currency ~ '^[A-Z]{3}$'",
        name="ck_finance_accounts_currency",
    ),
    CheckConstraint(
        "status IN ('ACTIVE', 'ARCHIVED')",
        name="ck_finance_accounts_status",
    ),
    CheckConstraint(
        "(status = 'ACTIVE' AND archived_at IS NULL) OR "
        "(status = 'ARCHIVED' AND archived_at IS NOT NULL)",
        name="ck_finance_accounts_archive_state",
    ),
    CheckConstraint(
        "updated_at >= created_at AND "
        "(archived_at IS NULL OR archived_at >= created_at)",
        name="ck_finance_accounts_timestamps",
    ),
    ForeignKeyConstraint(
        ["residence_id", "installation_id"],
        ["household.residences.id", "household.residences.installation_id"],
        ondelete="RESTRICT",
        name="fk_finance_accounts_residence",
    ),
    ForeignKeyConstraint(
        ["residence_id", "owner_operator_id"],
        ["household.memberships.residence_id", "household.memberships.operator_id"],
        ondelete="RESTRICT",
        name="fk_finance_accounts_owner_membership",
    ),
    UniqueConstraint(
        "id",
        "installation_id",
        "residence_id",
        "owner_operator_id",
        "visibility_scope",
        name="uq_finance_accounts_scope",
    ),
    schema="finance",
)

Index(
    "ix_finance_accounts_residence_status",
    financial_accounts.c.residence_id,
    financial_accounts.c.status,
    financial_accounts.c.created_at,
    financial_accounts.c.id,
)
Index(
    "ix_finance_accounts_owner",
    financial_accounts.c.residence_id,
    financial_accounts.c.owner_operator_id,
    financial_accounts.c.status,
)

financial_account_grants = Table(
    "account_grants",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("account_id", UUID(as_uuid=True), nullable=False),
    Column("owner_operator_id", UUID(as_uuid=True), nullable=False),
    Column("visibility_scope", String(16), nullable=False),
    Column("operator_id", UUID(as_uuid=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "visibility_scope = 'SHARED'",
        name="ck_finance_account_grants_shared",
    ),
    CheckConstraint(
        "operator_id <> owner_operator_id",
        name="ck_finance_account_grants_not_owner",
    ),
    ForeignKeyConstraint(
        [
            "account_id",
            "installation_id",
            "residence_id",
            "owner_operator_id",
            "visibility_scope",
        ],
        [
            "finance.accounts.id",
            "finance.accounts.installation_id",
            "finance.accounts.residence_id",
            "finance.accounts.owner_operator_id",
            "finance.accounts.visibility_scope",
        ],
        ondelete="CASCADE",
        name="fk_finance_account_grants_account_scope",
    ),
    ForeignKeyConstraint(
        ["residence_id", "operator_id"],
        ["household.memberships.residence_id", "household.memberships.operator_id"],
        ondelete="RESTRICT",
        name="fk_finance_account_grants_membership",
    ),
    UniqueConstraint(
        "account_id",
        "operator_id",
        name="uq_finance_account_grants_account_operator",
    ),
    schema="finance",
)

Index(
    "ix_finance_account_grants_operator",
    financial_account_grants.c.residence_id,
    financial_account_grants.c.operator_id,
    financial_account_grants.c.account_id,
)
Index(
    "ix_finance_account_grants_owner",
    financial_account_grants.c.residence_id,
    financial_account_grants.c.owner_operator_id,
    financial_account_grants.c.account_id,
)

__all__ = [
    "financial_account_grants",
    "financial_accounts",
]
