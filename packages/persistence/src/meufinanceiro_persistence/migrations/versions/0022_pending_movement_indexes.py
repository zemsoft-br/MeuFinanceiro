# mypy: ignore-errors
"""Add partial indexes for the derived pending-classification inbox.

Performance only. No table, column, grant, policy or trigger is created or
changed and no pending state is persisted: the inbox stays a read model derived
from ``finance.movements`` and ``finance.movement_allocation_sets``. The indexes
serve the ordered keyset scan (``effective_date DESC, id DESC``) over classifiable
Movements, residence-wide and per account, so a page stops after its limit instead
of sorting the whole residence.

Revision ID: 0022_pending_movement_indexes
Revises: 0021_categorization_rules
Create Date: 2026-10-05
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0022_pending_movement_indexes"
down_revision: str | None = "0021_categorization_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CLASSIFIABLE = "role = 'STANDARD' AND result_effect IN ('INCOME', 'EXPENSE')"


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_finance_movements_pending_scan "
        "ON finance.movements (residence_id, effective_date DESC, id DESC) "
        f"WHERE {_CLASSIFIABLE}"
    )
    op.execute(
        "CREATE INDEX ix_finance_movements_pending_account_scan "
        "ON finance.movements (residence_id, account_id, effective_date DESC, id DESC) "
        f"WHERE {_CLASSIFIABLE}"
    )


def downgrade() -> None:
    op.execute("DROP INDEX finance.ix_finance_movements_pending_account_scan")
    op.execute("DROP INDEX finance.ix_finance_movements_pending_scan")
