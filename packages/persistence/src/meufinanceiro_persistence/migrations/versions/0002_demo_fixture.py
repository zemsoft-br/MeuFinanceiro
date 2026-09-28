# mypy: ignore-errors
"""Create deterministic demonstration fixture metadata.

Revision ID: 0002_demo_fixture
Revises: 0001_persistence_queue
Create Date: 2026-07-22
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0002_demo_fixture"
down_revision: str | None = "0001_persistence_queue"
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
    op.create_table(
        "demo_fixture",
        sa.Column("fixture_id", sa.String(length=100), nullable=False),
        sa.Column("fixture_version", sa.Integer(), nullable=False),
        sa.Column("reference_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("contract_checksum", sa.String(length=64), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "fixture_version > 0",
            name="ck_demo_fixture_version_positive",
        ),
        sa.CheckConstraint(
            "contract_checksum ~ '^[0-9a-f]{64}$'",
            name="ck_demo_fixture_checksum_sha256",
        ),
        sa.PrimaryKeyConstraint("fixture_id"),
        schema="infra",
    )
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE infra.demo_fixture TO {role}"
    )


def downgrade() -> None:
    role = _quoted_role()
    op.execute(
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE infra.demo_fixture FROM {role}"
    )
    op.drop_table("demo_fixture", schema="infra")
