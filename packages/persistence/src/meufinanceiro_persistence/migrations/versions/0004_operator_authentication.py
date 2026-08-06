# mypy: ignore-errors
"""Create local installation operator authentication and opaque sessions.

Revision ID: 0004_operator_authentication
Revises: 0003_banking_persistence
Create Date: 2026-08-05
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0004_operator_authentication"
down_revision: str | None = "0003_banking_persistence"
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
    op.execute("CREATE SCHEMA IF NOT EXISTS identity")
    op.create_table(
        "installation",
        sa.Column("singleton", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("singleton", name="ck_identity_installation_singleton"),
        sa.PrimaryKeyConstraint("singleton"),
        sa.UniqueConstraint("id", name="uq_identity_installation_id"),
        schema="identity",
    )
    op.create_table(
        "operators",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("login_name", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_authenticated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "login_name ~ '^[a-z0-9][a-z0-9._-]{2,63}$'",
            name="ck_identity_operators_login",
        ),
        sa.CheckConstraint(
            "role = 'installation_admin'",
            name="ck_identity_operators_role",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_identity_operators_status",
        ),
        sa.CheckConstraint(
            "failed_attempts >= 0",
            name="ck_identity_operators_failed_attempts",
        ),
        sa.CheckConstraint(
            "length(password_hash) BETWEEN 32 AND 1024",
            name="ck_identity_operators_password_hash_length",
        ),
        sa.ForeignKeyConstraint(
            ["installation_id"],
            ["identity.installation.id"],
            ondelete="RESTRICT",
            name="fk_identity_operators_installation",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("login_name", name="uq_identity_operators_login"),
        sa.UniqueConstraint(
            "id",
            "installation_id",
            name="uq_identity_operators_installation_scope",
        ),
        schema="identity",
    )
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'",
            name="ck_identity_sessions_token_hash",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_identity_sessions_expiration",
        ),
        sa.CheckConstraint(
            "last_seen_at >= created_at",
            name="ck_identity_sessions_last_seen",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_identity_sessions_revoked_at",
        ),
        sa.ForeignKeyConstraint(
            ["operator_id", "installation_id"],
            ["identity.operators.id", "identity.operators.installation_id"],
            ondelete="CASCADE",
            name="fk_identity_sessions_operator_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_identity_sessions_token_hash"),
        schema="identity",
    )
    op.create_index(
        "ix_identity_sessions_operator_expiration",
        "sessions",
        ["operator_id", "expires_at"],
        unique=False,
        schema="identity",
    )
    op.execute(f"GRANT USAGE ON SCHEMA identity TO {role}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA identity TO {role}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA identity "
        f"GRANT SELECT, INSERT, UPDATE ON TABLES TO {role}"
    )


def downgrade() -> None:
    role = _quoted_role()
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA identity "
        f"REVOKE SELECT, INSERT, UPDATE ON TABLES FROM {role}"
    )
    op.execute(
        f"REVOKE SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA identity FROM {role}"
    )
    op.execute(f"REVOKE USAGE ON SCHEMA identity FROM {role}")
    op.drop_index(
        "ix_identity_sessions_operator_expiration",
        table_name="sessions",
        schema="identity",
    )
    op.drop_table("sessions", schema="identity")
    op.drop_table("operators", schema="identity")
    op.drop_table("installation", schema="identity")
    op.execute("DROP SCHEMA IF EXISTS identity")
