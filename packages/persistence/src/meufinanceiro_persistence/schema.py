"""SQLAlchemy Core metadata shared by queue operations and migrations."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

task_queue = Table(
    "task_queue",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("task_type", String(100), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("status", String(16), nullable=False),
    Column("idempotency_key", String(200), nullable=False),
    Column("correlation_id", UUID(as_uuid=True), nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("max_attempts", Integer, nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("locked_at", DateTime(timezone=True), nullable=True),
    Column("lease_expires_at", DateTime(timezone=True), nullable=True),
    Column("locked_by", String(200), nullable=True),
    Column("lease_token", UUID(as_uuid=True), nullable=True),
    Column("last_error", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    CheckConstraint(
        "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
        name="ck_task_queue_status",
    ),
    CheckConstraint("attempts >= 0", name="ck_task_queue_attempts_nonnegative"),
    CheckConstraint("max_attempts > 0", name="ck_task_queue_max_attempts_positive"),
    CheckConstraint(
        "(status = 'running' AND locked_at IS NOT NULL AND lease_expires_at IS NOT NULL "
        "AND locked_by IS NOT NULL AND lease_token IS NOT NULL) OR "
        "(status <> 'running' AND locked_at IS NULL AND lease_expires_at IS NULL "
        "AND locked_by IS NULL AND lease_token IS NULL)",
        name="ck_task_queue_lease_state",
    ),
    CheckConstraint(
        "(status IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NOT NULL) OR "
        "(status NOT IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NULL)",
        name="ck_task_queue_completion_state",
    ),
    UniqueConstraint("idempotency_key", name="uq_task_queue_idempotency_key"),
    schema="infra",
)

Index(
    "ix_task_queue_claimable",
    task_queue.c.status,
    task_queue.c.available_at,
    task_queue.c.created_at,
)


demo_task_effects = Table(
    "demo_task_effects",
    metadata,
    Column(
        "task_id",
        UUID(as_uuid=True),
        ForeignKey("infra.task_queue.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("message", String(500), nullable=False),
    schema="infra",
)
