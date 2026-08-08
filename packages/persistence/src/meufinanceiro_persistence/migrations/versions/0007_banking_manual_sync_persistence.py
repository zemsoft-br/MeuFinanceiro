# mypy: ignore-errors
"""Create residence-scoped manual sync runs, external accounts and cursors.

Revision ID: 0007_banking_manual_sync_persistence
Revises: 0006_banking_residence_fk
Create Date: 2026-08-08
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0007_banking_manual_sync_persistence"
down_revision: str | None = "0006_banking_residence_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


def _quoted_role() -> str:
    role_name = context.config.get_main_option("app_database_user")
    if not _ROLE_PATTERN.fullmatch(role_name):
        raise RuntimeError("invalid app_database_user for migration grants")
    return f'"{role_name}"'


def _create_sync_runs() -> None:
    op.create_table(
        "sync_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("residence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_category", sa.String(length=32), nullable=True),
        sa.Column("provider_reason_code", sa.String(length=128), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("retry_window_bucket", sa.String(length=32), nullable=True),
        sa.Column("records_seen", sa.Integer(), nullable=False),
        sa.Column("records_applied", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("trigger IN ('manual')", name="ck_sync_runs_trigger"),
        sa.CheckConstraint(
            "status IN ('requested', 'running', 'partial', 'succeeded', 'failed', 'cancelled')",
            name="ck_sync_runs_status",
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$'",
            name="ck_sync_runs_idempotency_key",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_sync_runs_attempt_count"),
        sa.CheckConstraint("records_seen >= 0", name="ck_sync_runs_records_seen"),
        sa.CheckConstraint("records_applied >= 0", name="ck_sync_runs_records_applied"),
        sa.CheckConstraint(
            "records_applied <= records_seen",
            name="ck_sync_runs_records_applied_seen",
        ),
        sa.CheckConstraint(
            "(status IN ('partial', 'succeeded', 'failed', 'cancelled') AND finished_at IS NOT NULL) OR "
            "(status IN ('requested', 'running') AND finished_at IS NULL)",
            name="ck_sync_runs_finished_at",
        ),
        sa.CheckConstraint(
            "status <> 'running' OR started_at IS NOT NULL",
            name="ck_sync_runs_running_started_at",
        ),
        sa.CheckConstraint(
            "error_category IS NULL OR error_category IN ("
            "'AUTHENTICATION', 'AUTHORIZATION', 'NOT_FOUND', 'INVALID_REQUEST', "
            "'REQUIRES_USER_ACTION', 'RATE_LIMITED', 'TEMPORARILY_UNAVAILABLE', "
            "'CONFLICT', 'UNSUPPORTED', 'INTERNAL')",
            name="ck_sync_runs_error_category",
        ),
        sa.CheckConstraint(
            "provider_reason_code IS NULL OR "
            "provider_reason_code ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'",
            name="ck_sync_runs_provider_reason_code",
        ),
        sa.CheckConstraint(
            "http_status IS NULL OR (http_status >= 100 AND http_status <= 599)",
            name="ck_sync_runs_http_status",
        ),
        sa.CheckConstraint(
            "retry_window_bucket IS NULL OR "
            "retry_window_bucket ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,31}$'",
            name="ck_sync_runs_retry_window_bucket",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "residence_id"],
            ["integrations.connections.id", "integrations.connections.residence_id"],
            ondelete="RESTRICT",
            name="fk_sync_runs_connection_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "idempotency_key",
            name="uq_sync_runs_connection_idempotency",
        ),
        schema="integrations",
    )
    op.create_index(
        "uq_sync_runs_one_active_per_connection",
        "sync_runs",
        ["connection_id"],
        unique=True,
        schema="integrations",
        postgresql_where=sa.text("status IN ('requested', 'running')"),
    )
    op.create_index(
        "ix_sync_runs_residence_created",
        "sync_runs",
        ["residence_id", "created_at"],
        unique=False,
        schema="integrations",
    )


def _create_external_accounts() -> None:
    op.create_table(
        "external_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("residence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_account_id", sa.String(length=512), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("subtype", sa.String(length=128), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=True),
        sa.Column("number_mask", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "type IN ('BANK', 'CREDIT', 'INVESTMENT', 'LOAN', 'OTHER')",
            name="ck_external_accounts_type",
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="ck_external_accounts_currency",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'unavailable', 'disconnected')",
            name="ck_external_accounts_status",
        ),
        sa.CheckConstraint(
            "length(external_account_id) BETWEEN 1 AND 512",
            name="ck_external_accounts_external_id_length",
        ),
        sa.CheckConstraint(
            "length(subtype) BETWEEN 1 AND 128",
            name="ck_external_accounts_subtype_length",
        ),
        sa.CheckConstraint(
            "name IS NULL OR length(name) BETWEEN 1 AND 512",
            name="ck_external_accounts_name_length",
        ),
        sa.CheckConstraint(
            "number_mask IS NULL OR length(number_mask) BETWEEN 1 AND 32",
            name="ck_external_accounts_number_mask_length",
        ),
        sa.CheckConstraint(
            "last_seen_at >= first_seen_at",
            name="ck_external_accounts_seen_order",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "residence_id"],
            ["integrations.connections.id", "integrations.connections.residence_id"],
            ondelete="RESTRICT",
            name="fk_external_accounts_connection_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "external_account_id",
            name="uq_external_accounts_connection_external",
        ),
        sa.UniqueConstraint(
            "connection_id",
            "residence_id",
            "external_account_id",
            name="uq_external_accounts_scope",
        ),
        schema="integrations",
    )
    op.create_index(
        "ix_external_accounts_residence_connection",
        "external_accounts",
        ["residence_id", "connection_id"],
        unique=False,
        schema="integrations",
    )


def _create_sync_cursors() -> None:
    op.create_table(
        "sync_cursors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("residence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_account_id", sa.String(length=512), nullable=False),
        sa.Column("resource", sa.String(length=32), nullable=False),
        sa.Column("cursor", sa.String(length=512), nullable=False),
        sa.Column("source_window", sa.String(length=256), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "resource IN ('transactions')",
            name="ck_sync_cursors_resource",
        ),
        sa.CheckConstraint(
            "length(cursor) BETWEEN 1 AND 512",
            name="ck_sync_cursors_cursor_length",
        ),
        sa.CheckConstraint(
            "length(source_window) BETWEEN 1 AND 256",
            name="ck_sync_cursors_source_window_length",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "residence_id", "external_account_id"],
            [
                "integrations.external_accounts.connection_id",
                "integrations.external_accounts.residence_id",
                "integrations.external_accounts.external_account_id",
            ],
            ondelete="RESTRICT",
            name="fk_sync_cursors_external_account_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "external_account_id",
            "resource",
            name="uq_sync_cursors_account_resource",
        ),
        schema="integrations",
    )
    op.create_index(
        "ix_sync_cursors_residence_connection",
        "sync_cursors",
        ["residence_id", "connection_id"],
        unique=False,
        schema="integrations",
    )


def _enable_rls() -> None:
    residence_expression = (
        "residence_id = NULLIF("
        "current_setting('app.current_residence_id', true), '')::uuid"
    )
    for table_name in ("sync_runs", "external_accounts", "sync_cursors"):
        op.execute(
            f"ALTER TABLE integrations.{table_name} ENABLE ROW LEVEL SECURITY"
        )
        op.execute(
            f"ALTER TABLE integrations.{table_name} FORCE ROW LEVEL SECURITY"
        )
        op.execute(
            f"CREATE POLICY {table_name}_residence_isolation "
            f"ON integrations.{table_name} "
            f"USING ({residence_expression}) "
            f"WITH CHECK ({residence_expression})"
        )


def upgrade() -> None:
    role = _quoted_role()
    _create_sync_runs()
    _create_external_accounts()
    _create_sync_cursors()
    _enable_rls()
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON "
        f"integrations.sync_runs, integrations.external_accounts, "
        f"integrations.sync_cursors TO {role}"
    )


def downgrade() -> None:
    role = _quoted_role()
    op.execute(
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON "
        f"integrations.sync_runs, integrations.external_accounts, "
        f"integrations.sync_cursors FROM {role}"
    )
    op.drop_index(
        "ix_sync_cursors_residence_connection",
        table_name="sync_cursors",
        schema="integrations",
    )
    op.drop_table("sync_cursors", schema="integrations")
    op.drop_index(
        "ix_external_accounts_residence_connection",
        table_name="external_accounts",
        schema="integrations",
    )
    op.drop_table("external_accounts", schema="integrations")
    op.drop_index(
        "ix_sync_runs_residence_created",
        table_name="sync_runs",
        schema="integrations",
    )
    op.drop_index(
        "uq_sync_runs_one_active_per_connection",
        table_name="sync_runs",
        schema="integrations",
    )
    op.drop_table("sync_runs", schema="integrations")
