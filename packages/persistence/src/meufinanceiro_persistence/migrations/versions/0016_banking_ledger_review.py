# mypy: ignore-errors
"""Create explicit reconciled-transaction ledger review links.

Revision ID: 0016_banking_ledger_review
Revises: 0015_financial_transfers
Create Date: 2026-08-16
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0016_banking_ledger_review"
down_revision: str | None = "0015_financial_transfers"
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
        CREATE TABLE integrations.reconciled_transaction_ledger_links (
            id uuid PRIMARY KEY,
            installation_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            connection_id uuid NOT NULL,
            reconciled_transaction_id uuid NOT NULL,
            source_observation_id uuid NOT NULL,
            source_observation_updated_at timestamptz NOT NULL,
            decision varchar(32) NOT NULL,
            financial_account_id uuid,
            movement_id uuid,
            currency varchar(3) NOT NULL,
            movement_result_effect varchar(16),
            movement_role varchar(16),
            decided_by_operator_id uuid NOT NULL,
            decided_at timestamptz NOT NULL,
            idempotency_key uuid NOT NULL,
            request_digest char(64) NOT NULL,
            CONSTRAINT ck_banking_ledger_links_id_uuid4 CHECK (
                id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ),
            CONSTRAINT ck_banking_ledger_links_idempotency_uuid4 CHECK (
                idempotency_key::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ),
            CONSTRAINT ck_banking_ledger_links_decision CHECK (
                decision IN (
                    'IMPORT_AS_INCOME',
                    'IMPORT_AS_EXPENSE',
                    'LINK_EXISTING_MOVEMENT',
                    'IGNORE'
                )
            ),
            CONSTRAINT ck_banking_ledger_links_currency CHECK (
                currency ~ '^[A-Z]{3}$'
            ),
            CONSTRAINT ck_banking_ledger_links_request_digest CHECK (
                request_digest ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT ck_banking_ledger_links_shape CHECK (
                (
                    decision = 'IGNORE'
                    AND financial_account_id IS NULL
                    AND movement_id IS NULL
                    AND movement_result_effect IS NULL
                    AND movement_role IS NULL
                )
                OR (
                    decision = 'IMPORT_AS_INCOME'
                    AND financial_account_id IS NOT NULL
                    AND movement_id IS NOT NULL
                    AND movement_result_effect = 'INCOME'
                    AND movement_role = 'STANDARD'
                )
                OR (
                    decision = 'IMPORT_AS_EXPENSE'
                    AND financial_account_id IS NOT NULL
                    AND movement_id IS NOT NULL
                    AND movement_result_effect = 'EXPENSE'
                    AND movement_role = 'STANDARD'
                )
                OR (
                    decision = 'LINK_EXISTING_MOVEMENT'
                    AND financial_account_id IS NOT NULL
                    AND movement_id IS NOT NULL
                    AND movement_result_effect IN ('INCOME', 'EXPENSE', 'NEUTRAL')
                    AND movement_role = 'STANDARD'
                )
            ),
            CONSTRAINT fk_banking_ledger_links_residence_scope FOREIGN KEY (
                residence_id, installation_id
            ) REFERENCES household.residences (
                id, installation_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_banking_ledger_links_connection_scope FOREIGN KEY (
                connection_id, residence_id
            ) REFERENCES integrations.connections (
                id, residence_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_banking_ledger_links_reconciled_scope FOREIGN KEY (
                reconciled_transaction_id, connection_id, residence_id
            ) REFERENCES integrations.reconciled_transactions (
                id, connection_id, residence_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_banking_ledger_links_source_scope FOREIGN KEY (
                source_observation_id, connection_id, residence_id
            ) REFERENCES integrations.external_observations (
                id, connection_id, residence_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_banking_ledger_links_account_scope FOREIGN KEY (
                financial_account_id, installation_id, residence_id, currency
            ) REFERENCES finance.accounts (
                id, installation_id, residence_id, currency
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_banking_ledger_links_movement_scope FOREIGN KEY (
                movement_id,
                installation_id,
                residence_id,
                financial_account_id,
                currency,
                movement_result_effect,
                movement_role
            ) REFERENCES finance.movements (
                id,
                installation_id,
                residence_id,
                account_id,
                currency,
                result_effect,
                role
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_banking_ledger_links_operator_membership FOREIGN KEY (
                residence_id, decided_by_operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT uq_banking_ledger_links_reconciled_decision UNIQUE (
                reconciled_transaction_id, connection_id, residence_id
            ),
            CONSTRAINT uq_banking_ledger_links_idempotency UNIQUE (
                installation_id, idempotency_key
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_banking_ledger_links_residence_decided "
        "ON integrations.reconciled_transaction_ledger_links "
        "(residence_id, decided_at, id)"
    )
    op.execute(
        "CREATE INDEX ix_banking_ledger_links_movement "
        "ON integrations.reconciled_transaction_ledger_links "
        "(residence_id, movement_id)"
    )

    installation = (
        "NULLIF(current_setting('app.current_installation_id', true), '')::uuid"
    )
    residence = "NULLIF(current_setting('app.current_residence_id', true), '')::uuid"
    operator = "NULLIF(current_setting('app.current_operator_id', true), '')::uuid"
    membership = (
        "EXISTS (SELECT 1 FROM household.memberships hm "
        "WHERE hm.installation_id = reconciled_transaction_ledger_links.installation_id "
        "AND hm.residence_id = reconciled_transaction_ledger_links.residence_id "
        f"AND hm.operator_id = {operator} AND hm.status = 'active')"
    )
    visible_movement = (
        "EXISTS (SELECT 1 FROM finance.movements m "
        "WHERE m.id = reconciled_transaction_ledger_links.movement_id "
        "AND m.installation_id = reconciled_transaction_ledger_links.installation_id "
        "AND m.residence_id = reconciled_transaction_ledger_links.residence_id "
        "AND m.account_id = reconciled_transaction_ledger_links.financial_account_id "
        "AND m.currency = reconciled_transaction_ledger_links.currency "
        "AND m.result_effect = reconciled_transaction_ledger_links.movement_result_effect "
        "AND m.role = reconciled_transaction_ledger_links.movement_role)"
    )

    op.execute(
        "ALTER TABLE integrations.reconciled_transaction_ledger_links "
        "ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE integrations.reconciled_transaction_ledger_links "
        "FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY banking_ledger_links_select "
        "ON integrations.reconciled_transaction_ledger_links "
        "FOR SELECT USING ("
        f"installation_id = {installation} AND residence_id = {residence} "
        f"AND {membership} AND (decided_by_operator_id = {operator} "
        f"OR (movement_id IS NOT NULL AND {visible_movement})))"
    )
    op.execute(
        "CREATE POLICY banking_ledger_links_insert "
        "ON integrations.reconciled_transaction_ledger_links "
        "FOR INSERT WITH CHECK ("
        f"installation_id = {installation} AND residence_id = {residence} "
        f"AND decided_by_operator_id = {operator} AND {membership} "
        f"AND (movement_id IS NULL OR {visible_movement}))"
    )

    op.execute(
        f"REVOKE UPDATE, DELETE ON "
        f"integrations.reconciled_transaction_ledger_links FROM {role}"
    )
    op.execute(
        f"GRANT SELECT, INSERT ON "
        f"integrations.reconciled_transaction_ledger_links TO {role}"
    )


def downgrade() -> None:
    role = _quoted_role()
    op.execute(
        f"REVOKE SELECT, INSERT ON "
        f"integrations.reconciled_transaction_ledger_links FROM {role}"
    )
    op.execute("DROP TABLE integrations.reconciled_transaction_ledger_links")
