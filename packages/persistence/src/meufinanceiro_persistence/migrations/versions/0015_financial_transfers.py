# mypy: ignore-errors
"""Create append-only atomic internal financial transfers.

Revision ID: 0015_financial_transfers
Revises: 0014_financial_movements
Create Date: 2026-08-13
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0015_financial_transfers"
down_revision: str | None = "0014_financial_movements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


def _quoted_role() -> str:
    role_name = context.config.get_main_option("app_database_user")
    if not _ROLE_PATTERN.fullmatch(role_name):
        raise RuntimeError("invalid app_database_user for migration grants")
    return f'"{role_name}"'


def _movement_reversal_function(*, transfer_guard: bool) -> str:
    guard = ""
    if transfer_guard:
        guard = """
            SELECT t.id, l.direction
              INTO linked_transfer_id, original_direction
              FROM finance.transfer_legs l
              JOIN finance.transfers t ON t.id = l.transfer_id
             WHERE l.movement_id = NEW.reversal_of_id
               AND t.installation_id = NEW.installation_id
               AND t.residence_id = NEW.residence_id
               AND t.role = 'STANDARD';

            IF FOUND THEN
                SELECT rt.id
                  INTO linked_reversal_id
                  FROM finance.transfers rt
                  JOIN finance.transfer_legs rl
                    ON rl.transfer_id = rt.id
                 WHERE rt.installation_id = NEW.installation_id
                   AND rt.residence_id = NEW.residence_id
                   AND rt.role = 'REVERSAL'
                   AND rt.reversal_of_id = linked_transfer_id
                   AND rl.movement_id = NEW.id
                   AND rl.direction = CASE original_direction
                       WHEN 'SOURCE' THEN 'DESTINATION'
                       ELSE 'SOURCE'
                   END;

                IF linked_reversal_id IS NULL THEN
                    RAISE EXCEPTION 'transfer Movement requires atomic transfer reversal'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_finance_movement_transfer_reversal_required';
                END IF;
            END IF;
        """

    return f"""
        CREATE OR REPLACE FUNCTION finance.validate_movement_reversal_amount()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            original_amount numeric(24,8);
            linked_transfer_id uuid;
            original_direction varchar(16);
            linked_reversal_id uuid;
        BEGIN
            IF NEW.role <> 'REVERSAL' THEN
                RETURN NEW;
            END IF;

            SELECT m.amount
              INTO original_amount
              FROM finance.movements m
             WHERE m.id = NEW.reversal_of_id
               AND m.installation_id = NEW.installation_id
               AND m.residence_id = NEW.residence_id
               AND m.account_id = NEW.account_id
               AND m.currency = NEW.currency
               AND m.result_effect = NEW.result_effect
               AND m.role = 'STANDARD';

            IF NOT FOUND OR NEW.amount <> -original_amount THEN
                RAISE EXCEPTION 'invalid Movement reversal amount'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_movement_reversal_amount';
            END IF;

            {guard}
            RETURN NEW;
        END;
        $$
    """


def upgrade() -> None:
    role = _quoted_role()

    op.execute(
        """
        CREATE TABLE finance.transfers (
            id uuid PRIMARY KEY,
            installation_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            source_account_id uuid NOT NULL,
            destination_account_id uuid NOT NULL,
            currency varchar(3) NOT NULL,
            role varchar(16) NOT NULL,
            reversal_of_id uuid,
            created_by_operator_id uuid NOT NULL,
            idempotency_key uuid NOT NULL,
            request_digest varchar(64) NOT NULL,
            created_at timestamptz NOT NULL,
            CONSTRAINT ck_finance_transfers_id_uuid4 CHECK (
                id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ),
            CONSTRAINT ck_finance_transfers_idempotency_uuid4 CHECK (
                idempotency_key::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ),
            CONSTRAINT ck_finance_transfers_currency CHECK (
                currency ~ '^[A-Z]{3}$'
            ),
            CONSTRAINT ck_finance_transfers_distinct_accounts CHECK (
                source_account_id <> destination_account_id
            ),
            CONSTRAINT ck_finance_transfers_role CHECK (
                role IN ('STANDARD', 'REVERSAL')
            ),
            CONSTRAINT ck_finance_transfers_role_shape CHECK (
                (role = 'STANDARD' AND reversal_of_id IS NULL)
                OR (role = 'REVERSAL' AND reversal_of_id IS NOT NULL)
            ),
            CONSTRAINT ck_finance_transfers_request_digest CHECK (
                request_digest ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT fk_finance_transfers_source_account_scope FOREIGN KEY (
                source_account_id, installation_id, residence_id, currency
            ) REFERENCES finance.accounts (
                id, installation_id, residence_id, currency
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_transfers_destination_account_scope FOREIGN KEY (
                destination_account_id, installation_id, residence_id, currency
            ) REFERENCES finance.accounts (
                id, installation_id, residence_id, currency
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_transfers_reversal_target FOREIGN KEY (
                reversal_of_id
            ) REFERENCES finance.transfers (id) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_transfers_creator_membership FOREIGN KEY (
                residence_id, created_by_operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT uq_finance_transfers_idempotency UNIQUE (
                installation_id, idempotency_key
            ),
            CONSTRAINT uq_finance_transfers_one_reversal UNIQUE (
                reversal_of_id
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE finance.transfer_legs (
            transfer_id uuid NOT NULL,
            direction varchar(16) NOT NULL,
            movement_id uuid NOT NULL,
            CONSTRAINT pk_finance_transfer_legs PRIMARY KEY (
                transfer_id, direction
            ),
            CONSTRAINT ck_finance_transfer_legs_direction CHECK (
                direction IN ('SOURCE', 'DESTINATION')
            ),
            CONSTRAINT fk_finance_transfer_legs_transfer FOREIGN KEY (
                transfer_id
            ) REFERENCES finance.transfers (id) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_transfer_legs_movement FOREIGN KEY (
                movement_id
            ) REFERENCES finance.movements (id)
              ON DELETE RESTRICT
              DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT uq_finance_transfer_legs_movement UNIQUE (
                movement_id
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_finance_transfers_source_account "
        "ON finance.transfers "
        "(residence_id, source_account_id, created_at, id)"
    )
    op.execute(
        "CREATE INDEX ix_finance_transfers_destination_account "
        "ON finance.transfers "
        "(residence_id, destination_account_id, created_at, id)"
    )

    op.execute(
        """
        CREATE FUNCTION finance.validate_transfer_integrity()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            source_row finance.movements%ROWTYPE;
            destination_row finance.movements%ROWTYPE;
            original_transfer finance.transfers%ROWTYPE;
            original_source_movement_id uuid;
            original_destination_movement_id uuid;
        BEGIN
            SELECT m.*
              INTO source_row
              FROM finance.transfer_legs l
              JOIN finance.movements m ON m.id = l.movement_id
             WHERE l.transfer_id = NEW.id
               AND l.direction = 'SOURCE';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'transfer source Movement is missing'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_transfer_integrity';
            END IF;

            SELECT m.*
              INTO destination_row
              FROM finance.transfer_legs l
              JOIN finance.movements m ON m.id = l.movement_id
             WHERE l.transfer_id = NEW.id
               AND l.direction = 'DESTINATION';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'transfer destination Movement is missing'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_transfer_integrity';
            END IF;

            IF source_row.installation_id IS DISTINCT FROM NEW.installation_id
               OR destination_row.installation_id IS DISTINCT FROM NEW.installation_id
               OR source_row.residence_id IS DISTINCT FROM NEW.residence_id
               OR destination_row.residence_id IS DISTINCT FROM NEW.residence_id
               OR source_row.account_id IS DISTINCT FROM NEW.source_account_id
               OR destination_row.account_id IS DISTINCT FROM NEW.destination_account_id
               OR source_row.currency IS DISTINCT FROM NEW.currency
               OR destination_row.currency IS DISTINCT FROM NEW.currency
               OR source_row.created_by_operator_id IS DISTINCT FROM NEW.created_by_operator_id
               OR destination_row.created_by_operator_id IS DISTINCT FROM NEW.created_by_operator_id
               OR source_row.result_effect IS DISTINCT FROM 'NEUTRAL'
               OR destination_row.result_effect IS DISTINCT FROM 'NEUTRAL'
               OR source_row.amount >= 0
               OR destination_row.amount <= 0
               OR source_row.amount IS DISTINCT FROM -destination_row.amount
               OR source_row.effective_date IS DISTINCT FROM destination_row.effective_date
               OR source_row.competence_date IS DISTINCT FROM destination_row.competence_date
               OR source_row.description IS DISTINCT FROM destination_row.description
            THEN
                RAISE EXCEPTION 'transfer Movement legs are inconsistent'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_transfer_integrity';
            END IF;

            IF NEW.role = 'STANDARD' THEN
                IF source_row.role IS DISTINCT FROM 'STANDARD'
                   OR destination_row.role IS DISTINCT FROM 'STANDARD'
                THEN
                    RAISE EXCEPTION 'invalid STANDARD transfer legs'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_finance_transfer_integrity';
                END IF;
                RETURN NEW;
            END IF;

            SELECT t.*
              INTO original_transfer
              FROM finance.transfers t
             WHERE t.id = NEW.reversal_of_id
               AND t.installation_id = NEW.installation_id
               AND t.residence_id = NEW.residence_id
               AND t.role = 'STANDARD';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'transfer reversal target is invalid'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_transfer_integrity';
            END IF;

            SELECT l.movement_id
              INTO original_source_movement_id
              FROM finance.transfer_legs l
             WHERE l.transfer_id = original_transfer.id
               AND l.direction = 'SOURCE';
            SELECT l.movement_id
              INTO original_destination_movement_id
              FROM finance.transfer_legs l
             WHERE l.transfer_id = original_transfer.id
               AND l.direction = 'DESTINATION';

            IF original_source_movement_id IS NULL
               OR original_destination_movement_id IS NULL
               OR NEW.source_account_id IS DISTINCT FROM original_transfer.destination_account_id
               OR NEW.destination_account_id IS DISTINCT FROM original_transfer.source_account_id
               OR NEW.currency IS DISTINCT FROM original_transfer.currency
               OR source_row.role IS DISTINCT FROM 'REVERSAL'
               OR destination_row.role IS DISTINCT FROM 'REVERSAL'
               OR source_row.reversal_of_id IS DISTINCT FROM original_destination_movement_id
               OR destination_row.reversal_of_id IS DISTINCT FROM original_source_movement_id
               OR source_row.reversal_reason IS DISTINCT FROM destination_row.reversal_reason
            THEN
                RAISE EXCEPTION 'invalid REVERSAL transfer legs'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_transfer_integrity';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_finance_validate_transfer_integrity "
        "AFTER INSERT ON finance.transfers "
        "DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION finance.validate_transfer_integrity()"
    )

    op.execute(_movement_reversal_function(transfer_guard=True))

    installation = (
        "NULLIF(current_setting('app.current_installation_id', true), '')::uuid"
    )
    residence = "NULLIF(current_setting('app.current_residence_id', true), '')::uuid"
    operator = "NULLIF(current_setting('app.current_operator_id', true), '')::uuid"
    active_membership = (
        "EXISTS (SELECT 1 FROM household.memberships m "
        "WHERE m.installation_id = transfers.installation_id "
        "AND m.residence_id = transfers.residence_id "
        f"AND m.operator_id = {operator} AND m.status = 'active')"
    )
    visible_source = (
        "EXISTS (SELECT 1 FROM finance.accounts a "
        "WHERE a.id = transfers.source_account_id "
        "AND a.installation_id = transfers.installation_id "
        "AND a.residence_id = transfers.residence_id "
        "AND a.currency = transfers.currency)"
    )
    visible_destination = (
        "EXISTS (SELECT 1 FROM finance.accounts a "
        "WHERE a.id = transfers.destination_account_id "
        "AND a.installation_id = transfers.installation_id "
        "AND a.residence_id = transfers.residence_id "
        "AND a.currency = transfers.currency)"
    )
    owned_source = (
        "EXISTS (SELECT 1 FROM finance.accounts a "
        "WHERE a.id = transfers.source_account_id "
        "AND a.installation_id = transfers.installation_id "
        "AND a.residence_id = transfers.residence_id "
        "AND a.currency = transfers.currency "
        f"AND a.owner_operator_id = {operator} AND a.status = 'ACTIVE')"
    )
    owned_destination = (
        "EXISTS (SELECT 1 FROM finance.accounts a "
        "WHERE a.id = transfers.destination_account_id "
        "AND a.installation_id = transfers.installation_id "
        "AND a.residence_id = transfers.residence_id "
        "AND a.currency = transfers.currency "
        f"AND a.owner_operator_id = {operator} AND a.status = 'ACTIVE')"
    )

    op.execute("ALTER TABLE finance.transfers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finance.transfers FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY finance_transfers_select ON finance.transfers "
        "FOR SELECT USING ("
        f"transfers.installation_id = {installation} "
        f"AND transfers.residence_id = {residence} "
        f"AND {active_membership} "
        f"AND {visible_source} AND {visible_destination})"
    )
    op.execute(
        "CREATE POLICY finance_transfers_insert ON finance.transfers "
        "FOR INSERT WITH CHECK ("
        f"transfers.installation_id = {installation} "
        f"AND transfers.residence_id = {residence} "
        f"AND transfers.created_by_operator_id = {operator} "
        f"AND {active_membership} "
        f"AND {owned_source} AND {owned_destination})"
    )

    op.execute("ALTER TABLE finance.transfer_legs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finance.transfer_legs FORCE ROW LEVEL SECURITY")
    parent_visible = (
        "EXISTS (SELECT 1 FROM finance.transfers t "
        "WHERE t.id = transfer_legs.transfer_id)"
    )
    op.execute(
        "CREATE POLICY finance_transfer_legs_select ON finance.transfer_legs "
        f"FOR SELECT USING ({parent_visible})"
    )
    op.execute(
        "CREATE POLICY finance_transfer_legs_insert ON finance.transfer_legs "
        f"FOR INSERT WITH CHECK ({parent_visible})"
    )

    op.execute(f"GRANT SELECT, INSERT ON finance.transfers TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON finance.transfer_legs TO {role}")


def downgrade() -> None:
    role = _quoted_role()
    op.execute(f"REVOKE SELECT, INSERT ON finance.transfer_legs FROM {role}")
    op.execute(f"REVOKE SELECT, INSERT ON finance.transfers FROM {role}")
    op.execute(_movement_reversal_function(transfer_guard=False))
    op.execute(
        "DROP TRIGGER trg_finance_validate_transfer_integrity "
        "ON finance.transfers"
    )
    op.execute("DROP FUNCTION finance.validate_transfer_integrity()")
    op.execute("DROP TABLE finance.transfer_legs")
    op.execute("DROP TABLE finance.transfers")
