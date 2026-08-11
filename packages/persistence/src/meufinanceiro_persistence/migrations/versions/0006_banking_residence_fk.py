# mypy: ignore-errors
"""Require banking connections to reference a canonical household residence.

Revision ID: 0006_banking_residence_fk
Revises: 0005_household_residences
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0006_banking_residence_fk"
down_revision: str | None = "0005_household_residences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT_NAME = "fk_connections_household_residence_scope"


def _lock_integrity_scope() -> None:
    op.execute(
        "LOCK TABLE household.residences, integrations.connections "
        "IN SHARE ROW EXCLUSIVE MODE"
    )


def _assert_no_orphan_connections() -> None:
    connection = op.get_bind()
    orphan_exists = connection.scalar(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM integrations.connections AS banking_connection
                LEFT JOIN household.residences AS residence
                  ON residence.id = banking_connection.residence_id
                 AND residence.installation_id = banking_connection.installation_id
                WHERE residence.id IS NULL
            )
            """
        )
    )
    if orphan_exists:
        raise RuntimeError(
            "banking connections contain non-canonical residence references"
        )


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("banking residence FK migration requires online validation")
    _lock_integrity_scope()
    _assert_no_orphan_connections()
    op.create_foreign_key(
        _CONSTRAINT_NAME,
        "connections",
        "residences",
        ["residence_id", "installation_id"],
        ["id", "installation_id"],
        source_schema="integrations",
        referent_schema="household",
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        _CONSTRAINT_NAME,
        "connections",
        schema="integrations",
        type_="foreignkey",
    )
