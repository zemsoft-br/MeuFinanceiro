"""SQLAlchemy metadata for residence-scoped banking sync fairness state."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Table,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from meufinanceiro_persistence.schema import external_accounts, metadata

# The fairness membership references the local account UUID together with its trusted
# connection/residence scope. The database migration adds the same candidate key.
UniqueConstraint(
    external_accounts.c.id,
    external_accounts.c.connection_id,
    external_accounts.c.residence_id,
    name="uq_external_accounts_local_scope",
)

sync_cycles = Table(
    "sync_cycles",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("connection_id", UUID(as_uuid=True), nullable=False),
    Column("status", String(16), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "status IN ('open', 'completed')",
        name="ck_sync_cycles_status",
    ),
    CheckConstraint(
        "(status = 'completed' AND completed_at IS NOT NULL) OR "
        "(status = 'open' AND completed_at IS NULL)",
        name="ck_sync_cycles_completion_state",
    ),
    ForeignKeyConstraint(
        ["connection_id", "residence_id"],
        ["integrations.connections.id", "integrations.connections.residence_id"],
        ondelete="CASCADE",
        name="fk_sync_cycles_connection_scope",
    ),
    UniqueConstraint(
        "id",
        "connection_id",
        "residence_id",
        name="uq_sync_cycles_scope",
    ),
    schema="integrations",
)

Index(
    "uq_sync_cycles_one_open_per_connection",
    sync_cycles.c.connection_id,
    unique=True,
    postgresql_where=text("status = 'open'"),
)
Index(
    "ix_sync_cycles_residence_connection",
    sync_cycles.c.residence_id,
    sync_cycles.c.connection_id,
    sync_cycles.c.created_at,
)

sync_cycle_accounts = Table(
    "sync_cycle_accounts",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("cycle_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("connection_id", UUID(as_uuid=True), nullable=False),
    Column("external_account_record_id", UUID(as_uuid=True), nullable=False),
    Column("active_in_latest_snapshot", Boolean, nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["cycle_id", "connection_id", "residence_id"],
        [
            "integrations.sync_cycles.id",
            "integrations.sync_cycles.connection_id",
            "integrations.sync_cycles.residence_id",
        ],
        ondelete="CASCADE",
        name="fk_sync_cycle_accounts_cycle_scope",
    ),
    ForeignKeyConstraint(
        ["external_account_record_id", "connection_id", "residence_id"],
        [
            "integrations.external_accounts.id",
            "integrations.external_accounts.connection_id",
            "integrations.external_accounts.residence_id",
        ],
        ondelete="CASCADE",
        name="fk_sync_cycle_accounts_external_account_scope",
    ),
    UniqueConstraint(
        "cycle_id",
        "external_account_record_id",
        name="uq_sync_cycle_accounts_cycle_account",
    ),
    schema="integrations",
)

Index(
    "ix_sync_cycle_accounts_active_pending",
    sync_cycle_accounts.c.residence_id,
    sync_cycle_accounts.c.connection_id,
    sync_cycle_accounts.c.cycle_id,
    postgresql_where=text("active_in_latest_snapshot AND completed_at IS NULL"),
)
