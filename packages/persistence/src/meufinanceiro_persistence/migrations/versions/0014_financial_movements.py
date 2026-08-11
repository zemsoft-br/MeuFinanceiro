# mypy: ignore-errors
"""Create append-only canonical financial Movements.

Revision ID: 0014_financial_movements
Revises: 0013_opening_balances
Create Date: 2026-08-11
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0014_financial_movements"
down_revision: str | None = "0013_opening_balances"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")
_LOCK_FUNCTION = (
    "finance.lock_standard_movement_for_reversal(uuid, uuid, uuid, uuid)"
)


def _quoted_role() -> str:
    role_name = context.config.get_main_option("app_database_user")
    if not _ROLE_PATTERN.fullmatch(role_name):
        raise RuntimeError("invalid app_database_user for migration grants")
    return f'"{role_name}"'


def upgrade() -> None:
    role = _quoted_role()

    op.execute(
        """
        CREATE TABLE finance.movements (
            id uuid PRIMARY KEY,
            installation_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            account_id uuid NOT NULL,
            currency varchar(3) NOT NULL,
            amount numeric(24,8) NOT NULL,
            result_effect varchar(16) NOT NULL,
            role varchar(16) NOT NULL,
            effective_date date NOT NULL,
            competence_date date NOT NULL,
            description varchar(256),
            reversal_of_id uuid,
            reversal_target_role varchar(16),
            reversal_reason varchar(256),
            created_by_operator_id uuid NOT NULL,
            idempotency_key uuid NOT NULL,
            request_digest varchar(64) NOT NULL,
            created_at timestamptz NOT NULL,
            CONSTRAINT ck_finance_movements_id_uuid4 CHECK (
                id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ),
            CONSTRAINT ck_finance_movements_idempotency_uuid4 CHECK (
                idempotency_key::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ),
            CONSTRAINT ck_finance_movements_currency CHECK (
                currency ~ '^[A-Z]{3}$'
            ),
            CONSTRAINT ck_finance_movements_amount CHECK (
                amount <> 0
                AND amount::text NOT IN ('NaN', 'Infinity', '-Infinity')
            ),
            CONSTRAINT ck_finance_movements_result_effect CHECK (
                result_effect IN ('INCOME', 'EXPENSE', 'NEUTRAL')
            ),
            CONSTRAINT ck_finance_movements_role CHECK (
                role IN ('STANDARD', 'REVERSAL')
            ),
            CONSTRAINT ck_finance_movements_request_digest CHECK (
                request_digest ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT ck_finance_movements_standard_sign CHECK (
                role = 'REVERSAL'
                OR result_effect = 'NEUTRAL'
                OR (result_effect = 'INCOME' AND amount > 0)
                OR (result_effect = 'EXPENSE' AND amount < 0)
            ),
            CONSTRAINT ck_finance_movements_role_shape CHECK (
                (
                    role = 'STANDARD'
                    AND description IS NOT NULL
                    AND length(btrim(description)) BETWEEN 1 AND 256
                    AND reversal_of_id IS NULL
                    AND reversal_target_role IS NULL
                    AND reversal_reason IS NULL
                )
                OR
                (
                    role = 'REVERSAL'
                    AND description IS NULL
                    AND reversal_of_id IS NOT NULL
                    AND reversal_target_role = 'STANDARD'
                    AND reversal_reason IS NOT NULL
                    AND length(btrim(reversal_reason)) BETWEEN 1 AND 256
                )
            ),
            CONSTRAINT fk_finance_movements_account_scope FOREIGN KEY (
                account_id, installation_id, residence_id, currency
            ) REFERENCES finance.accounts (
                id, installation_id, residence_id, currency
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_movements_creator_membership FOREIGN KEY (
                residence_id, created_by_operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT uq_finance_movements_reversal_target UNIQUE (
                id, installation_id, residence_id, account_id,
                currency, result_effect, role
            ),
            CONSTRAINT fk_finance_movements_reversal_target FOREIGN KEY (
                reversal_of_id, installation_id, residence_id, account_id,
                currency, result_effect, reversal_target_role
            ) REFERENCES finance.movements (
                id, installation_id, residence_id, account_id,
                currency, result_effect, role
            ) ON DELETE RESTRICT,
            CONSTRAINT uq_finance_movements_idempotency UNIQUE (
                installation_id, idempotency_key
            ),
            CONSTRAINT uq_finance_movements_one_reversal UNIQUE (reversal_of_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_finance_movements_account_effective "
        "ON finance.movements "
        "(residence_id, account_id, effective_date, created_at, id)"
    )
    op.execute(
        "CREATE INDEX ix_finance_movements_account_competence "
        "ON finance.movements "
        "(residence_id, account_id, competence_date, created_at, id)"
    )

    op.execute(
        """
        CREATE FUNCTION finance.validate_movement_reversal_amount()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            original_amount numeric(24,8);
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

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_finance_validate_movement_reversal_amount "
        "BEFORE INSERT ON finance.movements "
        "FOR EACH ROW EXECUTE FUNCTION finance.validate_movement_reversal_amount()"
    )

    residence = (
        "NULLIF(current_setting('app.current_residence_id', true), '')::uuid"
    )
    operator = (
        "NULLIF(current_setting('app.current_operator_id', true), '')::uuid"
    )
    active_membership = (
        "EXISTS (SELECT 1 FROM household.memberships m "
        "WHERE m.residence_id = movements.residence_id "
        f"AND m.operator_id = {operator} AND m.status = 'active')"
    )
    visible_account = (
        "EXISTS (SELECT 1 FROM finance.accounts a "
        "WHERE a.id = movements.account_id "
        "AND a.installation_id = movements.installation_id "
        "AND a.residence_id = movements.residence_id "
        "AND a.currency = movements.currency)"
    )
    owned_active_account = (
        "EXISTS (SELECT 1 FROM finance.accounts a "
        "WHERE a.id = movements.account_id "
        "AND a.installation_id = movements.installation_id "
        "AND a.residence_id = movements.residence_id "
        "AND a.currency = movements.currency "
        f"AND a.owner_operator_id = {operator} AND a.status = 'ACTIVE')"
    )
    after_opening_anchor = (
        "NOT EXISTS (SELECT 1 FROM finance.account_opening_balances ob "
        "WHERE ob.account_id = movements.account_id "
        "AND ob.installation_id = movements.installation_id "
        "AND ob.residence_id = movements.residence_id "
        "AND ob.currency = movements.currency "
        "AND movements.effective_date < ob.effective_date)"
    )

    op.execute("ALTER TABLE finance.movements ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finance.movements FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY finance_movements_select ON finance.movements "
        "FOR SELECT USING ("
        f"movements.residence_id = {residence} "
        f"AND {active_membership} AND {visible_account})"
    )
    op.execute(
        "CREATE POLICY finance_movements_insert ON finance.movements "
        "FOR INSERT WITH CHECK ("
        f"movements.residence_id = {residence} "
        f"AND movements.created_by_operator_id = {operator} "
        f"AND {active_membership} AND {owned_active_account} "
        f"AND {after_opening_anchor})"
    )
    op.execute(
        "CREATE POLICY finance_movements_lock_update ON finance.movements "
        "FOR UPDATE USING ("
        f"movements.residence_id = {residence} "
        "AND movements.role = 'STANDARD' "
        f"AND {active_membership} AND {owned_active_account})"
    )

    op.execute(
        """
        CREATE FUNCTION finance.lock_standard_movement_for_reversal(
            p_movement_id uuid,
            p_installation_id uuid,
            p_residence_id uuid,
            p_operator_id uuid
        )
        RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            locked_id uuid;
        BEGIN
            IF p_installation_id IS DISTINCT FROM
                   NULLIF(pg_catalog.current_setting(
                       'app.current_installation_id', true
                   ), '')::uuid
               OR p_residence_id IS DISTINCT FROM
                   NULLIF(pg_catalog.current_setting(
                       'app.current_residence_id', true
                   ), '')::uuid
               OR p_operator_id IS DISTINCT FROM
                   NULLIF(pg_catalog.current_setting(
                       'app.current_operator_id', true
                   ), '')::uuid
            THEN
                RETURN FALSE;
            END IF;

            SELECT m.id
              INTO locked_id
              FROM finance.movements m
              JOIN finance.accounts a
                ON a.id = m.account_id
               AND a.installation_id = m.installation_id
               AND a.residence_id = m.residence_id
               AND a.currency = m.currency
              JOIN household.memberships hm
                ON hm.installation_id = m.installation_id
               AND hm.residence_id = m.residence_id
               AND hm.operator_id = p_operator_id
             WHERE m.id = p_movement_id
               AND m.installation_id = p_installation_id
               AND m.residence_id = p_residence_id
               AND m.role = 'STANDARD'
               AND a.owner_operator_id = p_operator_id
               AND a.status = 'ACTIVE'
               AND hm.status = 'active'
             FOR UPDATE OF m;

            RETURN locked_id IS NOT NULL;
        END;
        $$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {_LOCK_FUNCTION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_LOCK_FUNCTION} TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON finance.movements TO {role}")


def downgrade() -> None:
    role = _quoted_role()
    op.execute(f"REVOKE EXECUTE ON FUNCTION {_LOCK_FUNCTION} FROM {role}")
    op.execute(f"REVOKE SELECT, INSERT ON finance.movements FROM {role}")
    op.execute(f"DROP FUNCTION {_LOCK_FUNCTION}")
    op.execute(
        "DROP TRIGGER trg_finance_validate_movement_reversal_amount "
        "ON finance.movements"
    )
    op.execute("DROP FUNCTION finance.validate_movement_reversal_amount()")
    op.execute("DROP TABLE finance.movements")
