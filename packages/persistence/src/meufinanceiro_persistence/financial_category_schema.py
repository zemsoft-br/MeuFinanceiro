"""SQLAlchemy metadata for canonical financial category trees."""

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

financial_categories = Table(
    "categories",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("owner_operator_id", UUID(as_uuid=True), nullable=False),
    Column("visibility_scope", String(16), nullable=False),
    Column("parent_id", UUID(as_uuid=True), nullable=True),
    Column("name", String(96), nullable=False),
    Column("status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("disabled_at", DateTime(timezone=True), nullable=True),
    CheckConstraint(
        "id::text ~ "
        "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
        name="ck_finance_categories_id_uuid4",
    ),
    CheckConstraint(
        "visibility_scope IN ('PERSONAL', 'HOUSEHOLD')",
        name="ck_finance_categories_visibility",
    ),
    CheckConstraint(
        "length(btrim(name)) BETWEEN 1 AND 96",
        name="ck_finance_categories_name",
    ),
    CheckConstraint(
        "status IN ('ACTIVE', 'DISABLED')",
        name="ck_finance_categories_status",
    ),
    CheckConstraint(
        "(status = 'ACTIVE' AND disabled_at IS NULL) OR "
        "(status = 'DISABLED' AND disabled_at IS NOT NULL)",
        name="ck_finance_categories_disable_state",
    ),
    CheckConstraint(
        "updated_at >= created_at AND "
        "(disabled_at IS NULL OR disabled_at >= created_at)",
        name="ck_finance_categories_timestamps",
    ),
    CheckConstraint(
        "parent_id IS NULL OR parent_id <> id",
        name="ck_finance_categories_not_self_parent",
    ),
    ForeignKeyConstraint(
        ["residence_id", "installation_id"],
        ["household.residences.id", "household.residences.installation_id"],
        ondelete="RESTRICT",
        name="fk_finance_categories_residence",
    ),
    ForeignKeyConstraint(
        ["residence_id", "owner_operator_id"],
        ["household.memberships.residence_id", "household.memberships.operator_id"],
        ondelete="RESTRICT",
        name="fk_finance_categories_owner_membership",
    ),
    UniqueConstraint(
        "id",
        "installation_id",
        "residence_id",
        "owner_operator_id",
        "visibility_scope",
        name="uq_finance_categories_scope",
    ),
    ForeignKeyConstraint(
        [
            "parent_id",
            "installation_id",
            "residence_id",
            "owner_operator_id",
            "visibility_scope",
        ],
        [
            "finance.categories.id",
            "finance.categories.installation_id",
            "finance.categories.residence_id",
            "finance.categories.owner_operator_id",
            "finance.categories.visibility_scope",
        ],
        ondelete="RESTRICT",
        name="fk_finance_categories_parent_scope",
    ),
    schema="finance",
)

Index(
    "ix_finance_categories_residence_status",
    financial_categories.c.residence_id,
    financial_categories.c.status,
    financial_categories.c.name,
    financial_categories.c.id,
)
Index(
    "ix_finance_categories_parent",
    financial_categories.c.residence_id,
    financial_categories.c.parent_id,
    financial_categories.c.name,
    financial_categories.c.id,
)
Index(
    "ix_finance_categories_owner",
    financial_categories.c.residence_id,
    financial_categories.c.owner_operator_id,
    financial_categories.c.status,
)

__all__ = ["financial_categories"]
