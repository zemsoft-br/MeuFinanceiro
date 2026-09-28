# mypy: ignore-errors
"""Create residence-scoped normalized transaction observations.

Revision ID: 0008_banking_tx_observations
Revises: 0007_banking_manual_sync
Create Date: 2026-08-08
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0008_banking_tx_observations"
down_revision: str | None = "0007_banking_manual_sync"
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
        CREATE TABLE integrations.external_observations (
            id uuid PRIMARY KEY,
            residence_id uuid NOT NULL,
            connection_id uuid NOT NULL,
            external_account_id varchar(512) NOT NULL,
            resource_type varchar(32) NOT NULL,
            external_resource_id varchar(512) NULL,
            status varchar(16) NOT NULL,
            provider_updated_at timestamptz NULL,
            effective_date date NOT NULL,
            amount numeric(24,8) NOT NULL,
            currency varchar(3) NOT NULL,
            description varchar(512) NULL,
            category varchar(128) NULL,
            stable_fingerprint char(64) NOT NULL,
            first_seen_at timestamptz NOT NULL,
            last_seen_at timestamptz NOT NULL,
            deleted_at timestamptz NULL,
            normalized_payload_version integer NOT NULL,
            updated_at timestamptz NOT NULL,
            CONSTRAINT ck_external_observations_resource CHECK (
                resource_type = 'transactions'
            ),
            CONSTRAINT ck_external_observations_status CHECK (
                status IN ('CONFIRMED','PENDING','INFERRED','DELETED')
            ),
            CONSTRAINT ck_external_observations_external_id_shape CHECK (
                external_resource_id IS NULL OR (
                    length(external_resource_id) BETWEEN 1 AND 512 AND
                    external_resource_id = btrim(external_resource_id) AND
                    external_resource_id !~ '[[:cntrl:]]'
                )
            ),
            CONSTRAINT ck_external_observations_inferred_identity CHECK (
                status <> 'INFERRED' OR external_resource_id IS NULL
            ),
            CONSTRAINT ck_external_observations_amount_finite CHECK (
                amount::text NOT IN ('NaN','Infinity','-Infinity')
            ),
            CONSTRAINT ck_external_observations_currency CHECK (
                currency ~ '^[A-Z]{3}$'
            ),
            CONSTRAINT ck_external_observations_description_shape CHECK (
                description IS NULL OR (
                    length(description) BETWEEN 1 AND 512 AND
                    description = btrim(description) AND
                    description !~ '[[:cntrl:]]'
                )
            ),
            CONSTRAINT ck_external_observations_category_shape CHECK (
                category IS NULL OR (
                    length(category) BETWEEN 1 AND 128 AND
                    category = btrim(category) AND
                    category !~ '[[:cntrl:]]'
                )
            ),
            CONSTRAINT ck_external_observations_fingerprint CHECK (
                stable_fingerprint ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT ck_external_observations_seen_order CHECK (
                last_seen_at >= first_seen_at
            ),
            CONSTRAINT ck_external_observations_deleted_state CHECK (
                (status = 'DELETED' AND deleted_at IS NOT NULL) OR
                (status <> 'DELETED' AND deleted_at IS NULL)
            ),
            CONSTRAINT ck_external_observations_payload_version CHECK (
                normalized_payload_version = 1
            ),
            CONSTRAINT fk_external_observations_account_scope FOREIGN KEY (
                connection_id, residence_id, external_account_id
            ) REFERENCES integrations.external_accounts (
                connection_id, residence_id, external_account_id
            ) ON DELETE RESTRICT,
            CONSTRAINT uq_external_observations_fingerprint UNIQUE (
                connection_id, external_account_id, stable_fingerprint
            )
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_external_observations_external_resource "
        "ON integrations.external_observations "
        "(connection_id, external_account_id, external_resource_id) "
        "WHERE external_resource_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_external_observations_residence_account_date "
        "ON integrations.external_observations "
        "(residence_id, connection_id, external_account_id, effective_date)"
    )
    op.execute(
        "ALTER TABLE integrations.external_observations ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE integrations.external_observations FORCE ROW LEVEL SECURITY"
    )
    residence_expression = (
        "residence_id = NULLIF("
        "current_setting('app.current_residence_id', true), '')::uuid"
    )
    op.execute(
        "CREATE POLICY external_observations_residence_isolation "
        "ON integrations.external_observations "
        f"USING ({residence_expression}) WITH CHECK ({residence_expression})"
    )
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE "
        f"ON integrations.external_observations TO {role}"
    )


def downgrade() -> None:
    role = _quoted_role()
    op.execute(
        f"REVOKE SELECT, INSERT, UPDATE, DELETE "
        f"ON integrations.external_observations FROM {role}"
    )
    op.execute("DROP TABLE integrations.external_observations")
