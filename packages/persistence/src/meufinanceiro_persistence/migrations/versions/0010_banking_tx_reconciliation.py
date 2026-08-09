# mypy: ignore-errors
"""Create residence-scoped canonical transaction reconciliation state.

Revision ID: 0010_banking_tx_reconciliation
Revises: 0009_banking_sync_fairness
Create Date: 2026-08-09
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0010_banking_tx_reconciliation"
down_revision: str | None = "0009_banking_sync_fairness"
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
        "ALTER TABLE integrations.external_observations "
        "ADD CONSTRAINT uq_external_observations_local_scope "
        "UNIQUE (id, connection_id, residence_id)"
    )
    op.execute(
        "CREATE INDEX ix_external_observations_reconciliation_scan "
        "ON integrations.external_observations "
        "(residence_id, connection_id, updated_at, id)"
    )

    op.execute(
        """
        CREATE TABLE integrations.reconciled_transactions (
            id uuid PRIMARY KEY,
            residence_id uuid NOT NULL,
            connection_id uuid NOT NULL,
            external_account_record_id uuid NOT NULL,
            identity_kind varchar(16) NOT NULL,
            identity_digest varchar(64) NOT NULL,
            status varchar(16) NOT NULL,
            source_observation_id uuid NOT NULL,
            source_observed_at timestamptz NOT NULL,
            first_reconciled_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            CONSTRAINT ck_reconciled_transactions_identity_kind CHECK (
                identity_kind IN ('PROVIDER_ID', 'FINGERPRINT')
            ),
            CONSTRAINT ck_reconciled_transactions_identity_digest CHECK (
                identity_digest ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT ck_reconciled_transactions_status CHECK (
                status IN ('PENDING', 'CONFIRMED', 'INFERRED', 'DELETED')
            ),
            CONSTRAINT fk_reconciled_transactions_account_scope FOREIGN KEY (
                external_account_record_id, connection_id, residence_id
            ) REFERENCES integrations.external_accounts (
                id, connection_id, residence_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_reconciled_transactions_source_scope FOREIGN KEY (
                source_observation_id, connection_id, residence_id
            ) REFERENCES integrations.external_observations (
                id, connection_id, residence_id
            ) ON DELETE RESTRICT,
            CONSTRAINT uq_reconciled_transactions_scope UNIQUE (
                id, connection_id, residence_id
            ),
            CONSTRAINT uq_reconciled_transactions_identity UNIQUE (
                connection_id,
                external_account_record_id,
                identity_kind,
                identity_digest
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_reconciled_transactions_account_status "
        "ON integrations.reconciled_transactions "
        "(residence_id, connection_id, external_account_record_id, status)"
    )

    op.execute(
        """
        CREATE TABLE integrations.reconciled_transaction_sources (
            id uuid PRIMARY KEY,
            residence_id uuid NOT NULL,
            connection_id uuid NOT NULL,
            reconciled_transaction_id uuid NOT NULL,
            source_observation_id uuid NOT NULL,
            observation_updated_at timestamptz NOT NULL,
            first_reconciled_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            CONSTRAINT fk_reconciled_transaction_sources_target_scope FOREIGN KEY (
                reconciled_transaction_id, connection_id, residence_id
            ) REFERENCES integrations.reconciled_transactions (
                id, connection_id, residence_id
            ) ON DELETE CASCADE,
            CONSTRAINT fk_reconciled_transaction_sources_observation_scope FOREIGN KEY (
                source_observation_id, connection_id, residence_id
            ) REFERENCES integrations.external_observations (
                id, connection_id, residence_id
            ) ON DELETE RESTRICT,
            CONSTRAINT uq_reconciled_transaction_sources_observation UNIQUE (
                source_observation_id, connection_id, residence_id
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_reconciled_transaction_sources_target "
        "ON integrations.reconciled_transaction_sources "
        "(residence_id, connection_id, reconciled_transaction_id)"
    )

    residence_expression = (
        "residence_id = NULLIF("
        "current_setting('app.current_residence_id', true), '')::uuid"
    )
    for table_name in (
        "reconciled_transactions",
        "reconciled_transaction_sources",
    ):
        op.execute(f"ALTER TABLE integrations.{table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE integrations.{table_name} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table_name}_residence_isolation "
            f"ON integrations.{table_name} "
            f"USING ({residence_expression}) WITH CHECK ({residence_expression})"
        )

    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON "
        f"integrations.reconciled_transactions, "
        f"integrations.reconciled_transaction_sources TO {role}"
    )


def downgrade() -> None:
    role = _quoted_role()
    op.execute(
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON "
        f"integrations.reconciled_transactions, "
        f"integrations.reconciled_transaction_sources FROM {role}"
    )
    op.execute("DROP TABLE integrations.reconciled_transaction_sources")
    op.execute("DROP TABLE integrations.reconciled_transactions")
    op.execute("DROP INDEX integrations.ix_external_observations_reconciliation_scan")
    op.execute(
        "ALTER TABLE integrations.external_observations "
        "DROP CONSTRAINT uq_external_observations_local_scope"
    )
