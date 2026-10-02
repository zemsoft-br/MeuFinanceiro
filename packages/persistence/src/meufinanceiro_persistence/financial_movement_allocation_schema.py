"""SQLAlchemy metadata for append-only Movement classification and allocation."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from meufinanceiro_persistence.schema import metadata


financial_movement_allocation_sets = Table(
    "movement_allocation_sets",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("movement_id", UUID(as_uuid=True), nullable=False),
    Column("revision", Integer(), nullable=False),
    Column("supersedes_id", UUID(as_uuid=True), nullable=True),
    Column("created_by_operator_id", UUID(as_uuid=True), nullable=False),
    Column("idempotency_key", UUID(as_uuid=True), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "id::text ~ "
        "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
        name="ck_finance_allocation_sets_id_uuid4",
    ),
    CheckConstraint(
        "idempotency_key::text ~ "
        "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
        name="ck_finance_allocation_sets_idempotency_uuid4",
    ),
    CheckConstraint(
        "revision >= 1",
        name="ck_finance_allocation_sets_revision_positive",
    ),
    CheckConstraint(
        "(revision = 1 AND supersedes_id IS NULL) OR "
        "(revision > 1 AND supersedes_id IS NOT NULL)",
        name="ck_finance_allocation_sets_revision_shape",
    ),
    CheckConstraint(
        "request_digest ~ '^[0-9a-f]{64}$'",
        name="ck_finance_allocation_sets_request_digest",
    ),
    ForeignKeyConstraint(
        ["movement_id"],
        ["finance.movements.id"],
        ondelete="RESTRICT",
        name="fk_finance_allocation_sets_movement",
    ),
    ForeignKeyConstraint(
        ["supersedes_id"],
        ["finance.movement_allocation_sets.id"],
        ondelete="RESTRICT",
        name="fk_finance_allocation_sets_supersedes",
    ),
    ForeignKeyConstraint(
        ["residence_id", "created_by_operator_id"],
        ["household.memberships.residence_id", "household.memberships.operator_id"],
        ondelete="RESTRICT",
        name="fk_finance_allocation_sets_creator_membership",
    ),
    UniqueConstraint(
        "installation_id",
        "idempotency_key",
        name="uq_finance_allocation_sets_idempotency",
    ),
    UniqueConstraint(
        "movement_id",
        "revision",
        name="uq_finance_allocation_sets_movement_revision",
    ),
    UniqueConstraint(
        "supersedes_id",
        name="uq_finance_allocation_sets_one_successor",
    ),
    schema="finance",
)

financial_movement_allocations = Table(
    "movement_allocations",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("allocation_set_id", UUID(as_uuid=True), nullable=False),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("movement_id", UUID(as_uuid=True), nullable=False),
    Column("category_id", UUID(as_uuid=True), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("amount", Numeric(24, 8), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "id::text ~ "
        "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
        name="ck_finance_allocations_id_uuid4",
    ),
    CheckConstraint(
        "currency ~ '^[A-Z]{3}$'",
        name="ck_finance_allocations_currency",
    ),
    CheckConstraint(
        "amount <> 0 AND amount::text NOT IN ('NaN', 'Infinity', '-Infinity')",
        name="ck_finance_allocations_amount",
    ),
    ForeignKeyConstraint(
        ["allocation_set_id"],
        ["finance.movement_allocation_sets.id"],
        ondelete="RESTRICT",
        name="fk_finance_allocations_set",
    ),
    ForeignKeyConstraint(
        ["movement_id"],
        ["finance.movements.id"],
        ondelete="RESTRICT",
        name="fk_finance_allocations_movement",
    ),
    ForeignKeyConstraint(
        ["category_id"],
        ["finance.categories.id"],
        ondelete="RESTRICT",
        name="fk_finance_allocations_category",
    ),
    UniqueConstraint(
        "allocation_set_id",
        "category_id",
        name="uq_finance_allocations_set_category",
    ),
    schema="finance",
)

Index(
    "ix_finance_allocation_sets_movement_revision",
    financial_movement_allocation_sets.c.residence_id,
    financial_movement_allocation_sets.c.movement_id,
    financial_movement_allocation_sets.c.revision,
)
Index(
    "ix_finance_allocations_category",
    financial_movement_allocations.c.residence_id,
    financial_movement_allocations.c.category_id,
    financial_movement_allocations.c.movement_id,
)

__all__ = [
    "financial_movement_allocation_sets",
    "financial_movement_allocations",
]
