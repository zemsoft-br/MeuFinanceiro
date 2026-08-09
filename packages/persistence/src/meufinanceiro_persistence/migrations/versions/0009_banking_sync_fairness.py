# mypy: ignore-errors
"""Create residence-scoped multi-run banking sync fairness state.

Revision ID: 0009_banking_sync_fairness
Revises: 0008_banking_tx_observations
Create Date: 2026-08-09
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0009_banking_sync_fairness"
down_revision: str | None = "0008_banking_tx_observations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


def _quoted_role() -> str:
    role_name = context.config.get_main_option("app_database_user")
    if not _ROLE_PATTERN.fullmatch(role_name):
        raise RuntimeError("invalid app_database_user for migration grants")
    return f'"{role_name}"'


def upgrade() -> None:
    role = _quoted_role()
    op.execute(
        """
        CREATE TABLE integrations.sync_cycles (
            id uuid PRIMARY KEY,
            residence_id uuid NOT NULL,
            connection_id uuid NOT NULL,
            status varchar(16) NOT NULL,
            started_at timestamptz NOT NULL,
            completed_at timestamptz NULL,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            CONSTRAINT ck_sync_cycles_status CHECK (
                status IN ('open','completed')
            ),
            CONSTRAINT ck_sync_cycles_completion_state CHECK (
                (status = 'completed' AND completed_at IS NOT NULL) OR
                (status = 'open' AND completed_at IS NULL)
            ),
            CONSTRAINT fk_sync_cycles_connection_scope FOREIGN KEY (
                connection_id, residence_id
            ) REFERENCES integrations.connections (
                id, residence_id
            ) ON DELETE CASCADE,
            CONSTRAINT uq_sync_cycles_scope UNIQUE (
                id, connection_id, residence_id
            )
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_sync_cycles_one_open_per_connection "
        "ON integrations.sync_cycles (connection_id) WHERE status = 'open'"
    )
    op.execute(
        "CREATE INDEX ix_sync_cycles_residence_connection "
        "ON integrations.sync_cycles (residence_id, connection_id, created_at)"
    )

    op.execute(
        """
        CREATE TABLE integrations.sync_cycle_accounts (
            id uuid PRIMARY KEY,
            cycle_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            connection_id uuid NOT NULL,
            external_account_id varchar(512) NOT NULL,
            active_in_latest_snapshot boolean NOT NULL,
            completed_at timestamptz NULL,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            CONSTRAINT ck_sync_cycle_accounts_external_id_shape CHECK (
                length(external_account_id) BETWEEN 1 AND 512 AND
                external_account_id = btrim(external_account_id) AND
                external_account_id !~ '[[:cntrl:]]'
            ),
            CONSTRAINT fk_sync_cycle_accounts_cycle_scope FOREIGN KEY (
                cycle_id, connection_id, residence_id
            ) REFERENCES integrations.sync_cycles (
                id, connection_id, residence_id
            ) ON DELETE CASCADE,
            CONSTRAINT fk_sync_cycle_accounts_external_account_scope FOREIGN KEY (
                connection_id, residence_id, external_account_id
            ) REFERENCES integrations.external_accounts (
                connection_id, residence_id, external_account_id
            ) ON DELETE CASCADE,
            CONSTRAINT uq_sync_cycle_accounts_cycle_account UNIQUE (
                cycle_id, external_account_id
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_sync_cycle_accounts_active_pending "
        "ON integrations.sync_cycle_accounts "
        "(residence_id, connection_id, cycle_id) "
        "WHERE active_in_latest_snapshot AND completed_at IS NULL"
    )

    residence_expression = (
        "residence_id = NULLIF("
        "current_setting('app.current_residence_id', true), '')::uuid"
    )
    for table_name in ("sync_cycles", "sync_cycle_accounts"):
        op.execute(f"ALTER TABLE integrations.{table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE integrations.{table_name} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table_name}_residence_isolation "
            f"ON integrations.{table_name} "
            f"USING ({residence_expression}) WITH CHECK ({residence_expression})"
        )

    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON "
        f"integrations.sync_cycles, integrations.sync_cycle_accounts TO {role}"
    )


def downgrade() -> None:
    role = _quoted_role()
    op.execute(
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON "
        f"integrations.sync_cycles, integrations.sync_cycle_accounts FROM {role}"
    )
    op.execute("DROP TABLE integrations.sync_cycle_accounts")
    op.execute("DROP TABLE integrations.sync_cycles")
