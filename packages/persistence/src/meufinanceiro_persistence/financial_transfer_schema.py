"""SQLAlchemy metadata for append-only canonical financial transfers."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from meufinanceiro_persistence.schema import metadata

financial_transfers = Table(
    "transfers",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("source_account_id", UUID(as_uuid=True), nullable=False),
    Column("destination_account_id", UUID(as_uuid=True), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("role", String(16), nullable=False),
    Column("reversal_of_id", UUID(as_uuid=True), nullable=True),
    Column("created_by_operator_id", UUID(as_uuid=True), nullable=False),
    Column("idempotency_key", UUID(as_uuid=True), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "id::text ~ "
        "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
        name="ck_finance_transfers_id_uuid4",
    ),
    CheckConstraint(
        "idempotency_key::text ~ "
        "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
        name="ck_finance_transfers_idempotency_uuid4",
    ),
    CheckConstraint(
        "currency ~ '^[A-Z]{3}$'",
        name="ck_finance_transfers_currency",
    ),
    CheckConstraint(
        "source_account_id <> destination_account_id",
        name="ck_finance_transfers_distinct_accounts",
    ),
    CheckConstraint(
        "role IN ('STANDARD', 'REVERSAL')",
        name="ck_finance_transfers_role",
    ),
    CheckConstraint(
        "(role = 'STANDARD' AND reversal_of_id IS NULL) OR "
        "(role = 'REVERSAL' AND reversal_of_id IS NOT NULL)",
        name="ck_finance_transfers_role_shape",
    ),
    CheckConstraint(
        "request_digest ~ '^[0-9a-f]{64}$'",
        name="ck_finance_transfers_request_digest",
    ),
    ForeignKeyConstraint(
        ["source_account_id", "installation_id", "residence_id", "currency"],
        [
            "finance.accounts.id",
            "finance.accounts.installation_id",
            "finance.accounts.residence_id",
            "finance.accounts.currency",
        ],
        ondelete="RESTRICT",
        name="fk_finance_transfers_source_account_scope",
    ),
    ForeignKeyConstraint(
        [
            "destination_account_id",
            "installation_id",
            "residence_id",
            "currency",
        ],
        [
            "finance.accounts.id",
            "finance.accounts.installation_id",
            "finance.accounts.residence_id",
            "finance.accounts.currency",
        ],
        ondelete="RESTRICT",
        name="fk_finance_transfers_destination_account_scope",
    ),
    ForeignKeyConstraint(
        ["reversal_of_id"],
        ["finance.transfers.id"],
        ondelete="RESTRICT",
        name="fk_finance_transfers_reversal_target",
    ),
    ForeignKeyConstraint(
        ["residence_id", "created_by_operator_id"],
        ["household.memberships.residence_id", "household.memberships.operator_id"],
        ondelete="RESTRICT",
        name="fk_finance_transfers_creator_membership",
    ),
    UniqueConstraint(
        "installation_id",
        "idempotency_key",
        name="uq_finance_transfers_idempotency",
    ),
    UniqueConstraint(
        "reversal_of_id",
        name="uq_finance_transfers_one_reversal",
    ),
    schema="finance",
)

financial_transfer_legs = Table(
    "transfer_legs",
    metadata,
    Column("transfer_id", UUID(as_uuid=True), nullable=False),
    Column("direction", String(16), nullable=False),
    Column("movement_id", UUID(as_uuid=True), nullable=False),
    PrimaryKeyConstraint(
        "transfer_id",
        "direction",
        name="pk_finance_transfer_legs",
    ),
    CheckConstraint(
        "direction IN ('SOURCE', 'DESTINATION')",
        name="ck_finance_transfer_legs_direction",
    ),
    ForeignKeyConstraint(
        ["transfer_id"],
        ["finance.transfers.id"],
        ondelete="RESTRICT",
        name="fk_finance_transfer_legs_transfer",
    ),
    ForeignKeyConstraint(
        ["movement_id"],
        ["finance.movements.id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
        name="fk_finance_transfer_legs_movement",
    ),
    UniqueConstraint(
        "movement_id",
        name="uq_finance_transfer_legs_movement",
    ),
    schema="finance",
)

Index(
    "ix_finance_transfers_source_account",
    financial_transfers.c.residence_id,
    financial_transfers.c.source_account_id,
    financial_transfers.c.created_at,
    financial_transfers.c.id,
)
Index(
    "ix_finance_transfers_destination_account",
    financial_transfers.c.residence_id,
    financial_transfers.c.destination_account_id,
    financial_transfers.c.created_at,
    financial_transfers.c.id,
)

__all__ = ["financial_transfer_legs", "financial_transfers"]
