# mypy: ignore-errors
"""Create primary residences and operator memberships.

Revision ID: 0005_household_residences
Revises: 0004_operator_authentication
Create Date: 2026-08-06
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0005_household_residences"
down_revision: str | None = "0004_operator_authentication"
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
    op.execute("CREATE SCHEMA IF NOT EXISTS household")
    op.create_table(
        "residences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=96), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 96",
            name="ck_household_residences_name",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_household_residences_status",
        ),
        sa.ForeignKeyConstraint(
            ["installation_id"],
            ["identity.installation.id"],
            ondelete="RESTRICT",
            name="fk_household_residences_installation",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "installation_id",
            name="uq_household_residences_installation_scope",
        ),
        schema="household",
    )
    op.create_index(
        "ix_household_residences_installation_status",
        "residences",
        ["installation_id", "status"],
        unique=False,
        schema="household",
    )
    op.create_table(
        "memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("residence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('owner', 'administrator', 'member')",
            name="ck_household_memberships_role",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_household_memberships_status",
        ),
        sa.CheckConstraint(
            "NOT is_primary OR status = 'active'",
            name="ck_household_memberships_primary_active",
        ),
        sa.ForeignKeyConstraint(
            ["residence_id", "installation_id"],
            ["household.residences.id", "household.residences.installation_id"],
            ondelete="RESTRICT",
            name="fk_household_memberships_residence_scope",
        ),
        sa.ForeignKeyConstraint(
            ["operator_id", "installation_id"],
            ["identity.operators.id", "identity.operators.installation_id"],
            ondelete="RESTRICT",
            name="fk_household_memberships_operator_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "residence_id",
            "operator_id",
            name="uq_household_memberships_residence_operator",
        ),
        schema="household",
    )
    op.create_index(
        "ix_household_memberships_operator_status",
        "memberships",
        ["installation_id", "operator_id", "status"],
        unique=False,
        schema="household",
    )
    op.create_index(
        "uq_household_memberships_primary_operator",
        "memberships",
        ["operator_id"],
        unique=True,
        schema="household",
        postgresql_where=sa.text("is_primary AND status = 'active'"),
    )
    op.execute(f"GRANT USAGE ON SCHEMA household TO {role}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA household TO {role}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA household "
        f"GRANT SELECT, INSERT, UPDATE ON TABLES TO {role}"
    )


def downgrade() -> None:
    role = _quoted_role()
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA household "
        f"REVOKE SELECT, INSERT, UPDATE ON TABLES FROM {role}"
    )
    op.execute(
        f"REVOKE SELECT, INSERT, UPDATE "
        f"ON ALL TABLES IN SCHEMA household FROM {role}"
    )
    op.execute(f"REVOKE USAGE ON SCHEMA household FROM {role}")
    op.drop_index(
        "uq_household_memberships_primary_operator",
        table_name="memberships",
        schema="household",
    )
    op.drop_index(
        "ix_household_memberships_operator_status",
        table_name="memberships",
        schema="household",
    )
    op.drop_table("memberships", schema="household")
    op.drop_index(
        "ix_household_residences_installation_status",
        table_name="residences",
        schema="household",
    )
    op.drop_table("residences", schema="household")
    op.execute("DROP SCHEMA IF EXISTS household")
