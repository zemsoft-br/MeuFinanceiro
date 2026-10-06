# mypy: ignore-errors
"""Add the allocation-by-Movement index that serves the derived budget realized.

Performance only. No table, column, grant, policy or trigger is created or
changed and nothing about a budget is persisted: realized amounts stay derived at
read time from ``finance.movements`` and the current allocation set. The index
lets the realized aggregate reach the shares of each Movement of the budget month
directly (``movement_id``) instead of pairing allocations by category.

Revision ID: 0024_budget_realization_indexes
Revises: 0023_monthly_budgets
Create Date: 2026-10-05
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0024_budget_realization_indexes"
down_revision: str | None = "0023_monthly_budgets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_finance_allocations_movement "
        "ON finance.movement_allocations (residence_id, movement_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX finance.ix_finance_allocations_movement")
