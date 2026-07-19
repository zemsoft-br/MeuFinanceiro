# mypy: ignore-errors
"""Create the infrastructure task queue.

Revision ID: 0001_persistence_queue
Revises:
Create Date: 2026-07-19
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0001_persistence_queue"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


def _quoted_role() -> str:
    role_name = context.config.get_main_option("app_database_user")
    if not ROLE_PATTERN.fullmatch(role_name):
        raise RuntimeError("invalid app_database_user for migration grants")
    return f'"{role_name}"'


def upgrade() -> None:
    role = _quoted_role()
    op.execute("CREATE SCHEMA IF NOT EXISTS infra")
    op.create_table(
        "task_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_type", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=200), nullable=True),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_task_queue_status",
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name="ck_task_queue_attempts_nonnegative",
        ),
        sa.CheckConstraint(
            "max_attempts > 0",
            name="ck_task_queue_max_attempts_positive",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND locked_at IS NOT NULL AND lease_expires_at IS NOT NULL "
            "AND locked_by IS NOT NULL AND lease_token IS NOT NULL) OR "
            "(status <> 'running' AND locked_at IS NULL AND lease_expires_at IS NULL "
            "AND locked_by IS NULL AND lease_token IS NULL)",
            name="ck_task_queue_lease_state",
        ),
        sa.CheckConstraint(
            "(status IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NOT NULL) OR "
            "(status NOT IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NULL)",
            name="ck_task_queue_completion_state",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_task_queue_idempotency_key",
        ),
        schema="infra",
    )
    op.create_index(
        "ix_task_queue_claimable",
        "task_queue",
        ["status", "available_at", "created_at"],
        unique=False,
        schema="infra",
    )
    op.create_table(
        "demo_task_effects",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["infra.task_queue.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("task_id"),
        schema="infra",
    )
    op.execute(f"GRANT USAGE ON SCHEMA infra TO {role}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA infra TO {role}"
    )
    op.execute(f"GRANT SELECT ON TABLE public.alembic_version TO {role}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA infra "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}"
    )


def downgrade() -> None:
    role = _quoted_role()
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA infra "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {role}"
    )
    op.execute(f"REVOKE SELECT ON TABLE public.alembic_version FROM {role}")
    op.drop_table("demo_task_effects", schema="infra")
    op.drop_index("ix_task_queue_claimable", table_name="task_queue", schema="infra")
    op.drop_table("task_queue", schema="infra")
    op.execute("DROP SCHEMA IF EXISTS infra")
