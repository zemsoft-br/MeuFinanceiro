# mypy: ignore-errors
"""Create residence-scoped manual sync runs, external accounts and cursors.

Revision ID: 0007_banking_manual_sync
Revises: 0006_banking_residence_fk
Create Date: 2026-08-08
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0007_banking_manual_sync"
down_revision: str | None = "0006_banking_residence_fk"
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
        CREATE TABLE integrations.sync_runs (
            id uuid PRIMARY KEY,
            residence_id uuid NOT NULL,
            connection_id uuid NOT NULL,
            idempotency_key varchar(200) NOT NULL,
            trigger varchar(16) NOT NULL,
            status varchar(16) NOT NULL,
            started_at timestamptz NULL,
            finished_at timestamptz NULL,
            attempt_count integer NOT NULL,
            error_category varchar(32) NULL,
            provider_reason_code varchar(128) NULL,
            http_status integer NULL,
            retry_window_bucket varchar(32) NULL,
            records_seen integer NOT NULL,
            records_applied integer NOT NULL,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            CONSTRAINT ck_sync_runs_trigger CHECK (trigger = 'manual'),
            CONSTRAINT ck_sync_runs_status CHECK (
                status IN ('requested','running','partial','succeeded','failed','cancelled')
            ),
            CONSTRAINT ck_sync_runs_idempotency_key CHECK (
                idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$'
            ),
            CONSTRAINT ck_sync_runs_attempt_count CHECK (attempt_count >= 0),
            CONSTRAINT ck_sync_runs_records_seen CHECK (records_seen >= 0),
            CONSTRAINT ck_sync_runs_records_applied CHECK (records_applied >= 0),
            CONSTRAINT ck_sync_runs_records_applied_seen CHECK (records_applied <= records_seen),
            CONSTRAINT ck_sync_runs_finished_at CHECK (
                (status IN ('partial','succeeded','failed','cancelled') AND finished_at IS NOT NULL)
                OR (status IN ('requested','running') AND finished_at IS NULL)
            ),
            CONSTRAINT ck_sync_runs_running_started_at CHECK (
                status <> 'running' OR started_at IS NOT NULL
            ),
            CONSTRAINT ck_sync_runs_error_category CHECK (
                error_category IS NULL OR error_category IN (
                    'AUTHENTICATION','AUTHORIZATION','NOT_FOUND','INVALID_REQUEST',
                    'REQUIRES_USER_ACTION','RATE_LIMITED','TEMPORARILY_UNAVAILABLE',
                    'CONFLICT','UNSUPPORTED','INTERNAL'
                )
            ),
            CONSTRAINT ck_sync_runs_provider_reason_code CHECK (
                provider_reason_code IS NULL OR
                provider_reason_code ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'
            ),
            CONSTRAINT ck_sync_runs_http_status CHECK (
                http_status IS NULL OR http_status BETWEEN 100 AND 599
            ),
            CONSTRAINT ck_sync_runs_retry_window_bucket CHECK (
                retry_window_bucket IS NULL OR
                retry_window_bucket ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,31}$'
            ),
            CONSTRAINT ck_sync_runs_success_diagnostics CHECK (
                status <> 'succeeded' OR (
                    error_category IS NULL AND provider_reason_code IS NULL AND
                    http_status IS NULL AND retry_window_bucket IS NULL
                )
            ),
            CONSTRAINT fk_sync_runs_connection_scope FOREIGN KEY (connection_id, residence_id)
                REFERENCES integrations.connections (id, residence_id) ON DELETE RESTRICT,
            CONSTRAINT uq_sync_runs_connection_idempotency UNIQUE (connection_id, idempotency_key)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_sync_runs_one_active_per_connection "
        "ON integrations.sync_runs (connection_id) "
        "WHERE status IN ('requested','running')"
    )
    op.execute(
        "CREATE INDEX ix_sync_runs_residence_created "
        "ON integrations.sync_runs (residence_id, created_at)"
    )

    op.execute(
        """
        CREATE TABLE integrations.external_accounts (
            id uuid PRIMARY KEY,
            residence_id uuid NOT NULL,
            connection_id uuid NOT NULL,
            external_account_id varchar(512) NOT NULL,
            type varchar(16) NOT NULL,
            subtype varchar(128) NOT NULL,
            currency varchar(3) NOT NULL,
            name varchar(512) NULL,
            number_mask varchar(32) NULL,
            status varchar(16) NOT NULL,
            first_seen_at timestamptz NOT NULL,
            last_seen_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            CONSTRAINT ck_external_accounts_type CHECK (
                type IN ('BANK','CREDIT','INVESTMENT','LOAN','OTHER')
            ),
            CONSTRAINT ck_external_accounts_currency CHECK (currency ~ '^[A-Z]{3}$'),
            CONSTRAINT ck_external_accounts_status CHECK (
                status IN ('active','unavailable','disconnected')
            ),
            CONSTRAINT ck_external_accounts_external_id_shape CHECK (
                length(external_account_id) BETWEEN 1 AND 512 AND
                external_account_id = btrim(external_account_id) AND
                external_account_id !~ '[[:cntrl:]]'
            ),
            CONSTRAINT ck_external_accounts_subtype_shape CHECK (
                length(subtype) BETWEEN 1 AND 128 AND subtype = btrim(subtype) AND
                subtype !~ '[[:cntrl:]]'
            ),
            CONSTRAINT ck_external_accounts_name_shape CHECK (
                name IS NULL OR (
                    length(name) BETWEEN 1 AND 512 AND name = btrim(name) AND
                    name !~ '[[:cntrl:]]'
                )
            ),
            CONSTRAINT ck_external_accounts_number_mask_shape CHECK (
                number_mask IS NULL OR (
                    length(number_mask) BETWEEN 1 AND 32 AND
                    number_mask = btrim(number_mask) AND
                    number_mask !~ '[[:cntrl:]]' AND
                    length(regexp_replace(number_mask, '[^0-9]', '', 'g')) <= 4
                )
            ),
            CONSTRAINT ck_external_accounts_seen_order CHECK (last_seen_at >= first_seen_at),
            CONSTRAINT fk_external_accounts_connection_scope FOREIGN KEY (connection_id, residence_id)
                REFERENCES integrations.connections (id, residence_id) ON DELETE RESTRICT,
            CONSTRAINT uq_external_accounts_connection_external UNIQUE (connection_id, external_account_id),
            CONSTRAINT uq_external_accounts_scope UNIQUE (connection_id, residence_id, external_account_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_external_accounts_residence_connection "
        "ON integrations.external_accounts (residence_id, connection_id)"
    )

    op.execute(
        """
        CREATE TABLE integrations.sync_cursors (
            id uuid PRIMARY KEY,
            residence_id uuid NOT NULL,
            connection_id uuid NOT NULL,
            external_account_id varchar(512) NOT NULL,
            resource varchar(32) NOT NULL,
            cursor varchar(512) NOT NULL,
            source_window varchar(256) NOT NULL,
            committed_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            CONSTRAINT ck_sync_cursors_resource CHECK (resource = 'transactions'),
            CONSTRAINT ck_sync_cursors_cursor_shape CHECK (
                length(cursor) BETWEEN 1 AND 512 AND cursor = btrim(cursor) AND
                cursor !~ '[[:cntrl:]]'
            ),
            CONSTRAINT ck_sync_cursors_source_window_shape CHECK (
                length(source_window) BETWEEN 1 AND 256 AND
                source_window = btrim(source_window) AND source_window !~ '[[:cntrl:]]'
            ),
            CONSTRAINT fk_sync_cursors_external_account_scope FOREIGN KEY (
                connection_id, residence_id, external_account_id
            ) REFERENCES integrations.external_accounts (
                connection_id, residence_id, external_account_id
            ) ON DELETE RESTRICT,
            CONSTRAINT uq_sync_cursors_account_resource UNIQUE (
                connection_id, external_account_id, resource
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_sync_cursors_residence_connection "
        "ON integrations.sync_cursors (residence_id, connection_id)"
    )

    residence_expression = (
        "residence_id = NULLIF("
        "current_setting('app.current_residence_id', true), '')::uuid"
    )
    for table_name in ("sync_runs", "external_accounts", "sync_cursors"):
        op.execute(f"ALTER TABLE integrations.{table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE integrations.{table_name} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table_name}_residence_isolation "
            f"ON integrations.{table_name} "
            f"USING ({residence_expression}) WITH CHECK ({residence_expression})"
        )

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
    op.execute("DROP TABLE integrations.sync_cursors")
    op.execute("DROP TABLE integrations.external_accounts")
    op.execute("DROP TABLE integrations.sync_runs")
