# mypy: ignore-errors
"""Create append-only Movement classification and allocation persistence.

Revision ID: 0017_movement_allocations
Revises: 0016_banking_ledger_review
Create Date: 2026-08-17
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0017_movement_allocations"
down_revision: str | None = "0016_banking_ledger_review"
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
        CREATE TABLE finance.movement_allocation_sets (
            id uuid PRIMARY KEY,
            installation_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            movement_id uuid NOT NULL,
            revision integer NOT NULL,
            supersedes_id uuid,
            created_by_operator_id uuid NOT NULL,
            idempotency_key uuid NOT NULL,
            request_digest varchar(64) NOT NULL,
            created_at timestamptz NOT NULL,
            CONSTRAINT ck_finance_allocation_sets_id_uuid4 CHECK (
                id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ),
            CONSTRAINT ck_finance_allocation_sets_idempotency_uuid4 CHECK (
                idempotency_key::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ),
            CONSTRAINT ck_finance_allocation_sets_revision_positive CHECK (
                revision >= 1
            ),
            CONSTRAINT ck_finance_allocation_sets_revision_shape CHECK (
                (revision = 1 AND supersedes_id IS NULL)
                OR (revision > 1 AND supersedes_id IS NOT NULL)
            ),
            CONSTRAINT ck_finance_allocation_sets_request_digest CHECK (
                request_digest ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT fk_finance_allocation_sets_movement FOREIGN KEY (
                movement_id
            ) REFERENCES finance.movements (id) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_allocation_sets_supersedes FOREIGN KEY (
                supersedes_id
            ) REFERENCES finance.movement_allocation_sets (id) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_allocation_sets_creator_membership FOREIGN KEY (
                residence_id, created_by_operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT uq_finance_allocation_sets_idempotency UNIQUE (
                installation_id, idempotency_key
            ),
            CONSTRAINT uq_finance_allocation_sets_movement_revision UNIQUE (
                movement_id, revision
            ),
            CONSTRAINT uq_finance_allocation_sets_one_successor UNIQUE (
                supersedes_id
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE finance.movement_allocations (
            id uuid PRIMARY KEY,
            allocation_set_id uuid NOT NULL,
            installation_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            movement_id uuid NOT NULL,
            category_id uuid NOT NULL,
            currency varchar(3) NOT NULL,
            amount numeric(24,8) NOT NULL,
            created_at timestamptz NOT NULL,
            CONSTRAINT ck_finance_allocations_id_uuid4 CHECK (
                id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ),
            CONSTRAINT ck_finance_allocations_currency CHECK (
                currency ~ '^[A-Z]{3}$'
            ),
            CONSTRAINT ck_finance_allocations_amount CHECK (
                amount <> 0
                AND amount::text NOT IN ('NaN', 'Infinity', '-Infinity')
            ),
            CONSTRAINT fk_finance_allocations_set FOREIGN KEY (
                allocation_set_id
            ) REFERENCES finance.movement_allocation_sets (id) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_allocations_movement FOREIGN KEY (
                movement_id
            ) REFERENCES finance.movements (id) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_allocations_category FOREIGN KEY (
                category_id
            ) REFERENCES finance.categories (id) ON DELETE RESTRICT,
            CONSTRAINT uq_finance_allocations_set_category UNIQUE (
                allocation_set_id, category_id
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_finance_allocation_sets_movement_revision "
        "ON finance.movement_allocation_sets "
        "(residence_id, movement_id, revision)"
    )
    op.execute(
        "CREATE INDEX ix_finance_allocations_category "
        "ON finance.movement_allocations "
        "(residence_id, category_id, movement_id)"
    )

    op.execute(
        """
        CREATE FUNCTION finance.assert_movement_allocation_set(p_set_id uuid)
        RETURNS void
        LANGUAGE plpgsql
        AS $$
        DECLARE
            set_row finance.movement_allocation_sets%ROWTYPE;
            movement_row finance.movements%ROWTYPE;
            account_row finance.accounts%ROWTYPE;
            predecessor_row finance.movement_allocation_sets%ROWTYPE;
            allocation_row finance.movement_allocations%ROWTYPE;
            category_row finance.categories%ROWTYPE;
            allocation_count integer := 0;
            allocation_total numeric(24,8) := 0;
        BEGIN
            SELECT s.*
              INTO set_row
              FROM finance.movement_allocation_sets s
             WHERE s.id = p_set_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'allocation set is missing'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_allocation_set_integrity';
            END IF;

            SELECT m.*
              INTO movement_row
              FROM finance.movements m
             WHERE m.id = set_row.movement_id;
            IF NOT FOUND
               OR movement_row.installation_id IS DISTINCT FROM set_row.installation_id
               OR movement_row.residence_id IS DISTINCT FROM set_row.residence_id
               OR movement_row.role IS DISTINCT FROM 'STANDARD'
               OR movement_row.result_effect NOT IN ('INCOME', 'EXPENSE')
            THEN
                RAISE EXCEPTION 'allocation target Movement is not eligible'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_allocation_set_target';
            END IF;

            SELECT a.*
              INTO account_row
              FROM finance.accounts a
             WHERE a.id = movement_row.account_id;
            IF NOT FOUND
               OR account_row.installation_id IS DISTINCT FROM set_row.installation_id
               OR account_row.residence_id IS DISTINCT FROM set_row.residence_id
               OR account_row.currency IS DISTINCT FROM movement_row.currency
               OR account_row.status IS DISTINCT FROM 'ACTIVE'
               OR account_row.owner_operator_id
                    IS DISTINCT FROM set_row.created_by_operator_id
            THEN
                RAISE EXCEPTION 'allocation account is not eligible'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_allocation_set_account';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                  FROM household.memberships hm
                 WHERE hm.installation_id = set_row.installation_id
                   AND hm.residence_id = set_row.residence_id
                   AND hm.operator_id = set_row.created_by_operator_id
                   AND hm.status = 'active'
            ) THEN
                RAISE EXCEPTION 'allocation creator membership is not active'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_allocation_set_membership';
            END IF;

            IF set_row.revision = 1 THEN
                IF set_row.supersedes_id IS NOT NULL THEN
                    RAISE EXCEPTION 'first allocation revision has predecessor'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_finance_allocation_set_revision';
                END IF;
            ELSE
                SELECT s.*
                  INTO predecessor_row
                  FROM finance.movement_allocation_sets s
                 WHERE s.id = set_row.supersedes_id;
                IF NOT FOUND
                   OR predecessor_row.installation_id
                        IS DISTINCT FROM set_row.installation_id
                   OR predecessor_row.residence_id
                        IS DISTINCT FROM set_row.residence_id
                   OR predecessor_row.movement_id
                        IS DISTINCT FROM set_row.movement_id
                   OR set_row.revision <> predecessor_row.revision + 1
                THEN
                    RAISE EXCEPTION 'allocation predecessor is invalid'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_finance_allocation_set_revision';
                END IF;
            END IF;

            FOR allocation_row IN
                SELECT a.*
                  FROM finance.movement_allocations a
                 WHERE a.allocation_set_id = set_row.id
                 ORDER BY a.category_id
            LOOP
                allocation_count := allocation_count + 1;

                IF allocation_row.installation_id
                        IS DISTINCT FROM set_row.installation_id
                   OR allocation_row.residence_id
                        IS DISTINCT FROM set_row.residence_id
                   OR allocation_row.movement_id
                        IS DISTINCT FROM set_row.movement_id
                   OR allocation_row.currency
                        IS DISTINCT FROM movement_row.currency
                   OR allocation_row.amount = 0
                   OR (movement_row.amount > 0 AND allocation_row.amount <= 0)
                   OR (movement_row.amount < 0 AND allocation_row.amount >= 0)
                THEN
                    RAISE EXCEPTION 'allocation share is inconsistent'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_finance_allocation_share_integrity';
                END IF;

                SELECT c.*
                  INTO category_row
                  FROM finance.categories c
                 WHERE c.id = allocation_row.category_id;
                IF NOT FOUND
                   OR category_row.installation_id
                        IS DISTINCT FROM set_row.installation_id
                   OR category_row.residence_id
                        IS DISTINCT FROM set_row.residence_id
                   OR category_row.status IS DISTINCT FROM 'ACTIVE'
                THEN
                    RAISE EXCEPTION 'allocation category is not eligible'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_finance_allocation_category';
                END IF;

                IF category_row.visibility_scope = 'HOUSEHOLD' THEN
                    NULL;
                ELSIF account_row.visibility_scope = 'PERSONAL'
                      AND category_row.visibility_scope = 'PERSONAL'
                      AND category_row.owner_operator_id
                            = account_row.owner_operator_id
                THEN
                    NULL;
                ELSE
                    RAISE EXCEPTION 'allocation category audience is incompatible'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_finance_allocation_audience';
                END IF;

                allocation_total := allocation_total + allocation_row.amount;
            END LOOP;

            IF allocation_count < 1
               OR allocation_total IS DISTINCT FROM movement_row.amount
            THEN
                RAISE EXCEPTION 'allocation set does not close against Movement'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_allocation_set_total';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION finance.validate_movement_allocation_set_row()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            PERFORM finance.assert_movement_allocation_set(NEW.id);
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION finance.validate_movement_allocation_share_row()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            PERFORM finance.assert_movement_allocation_set(NEW.allocation_set_id);
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_finance_validate_allocation_set "
        "AFTER INSERT ON finance.movement_allocation_sets "
        "DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION "
        "finance.validate_movement_allocation_set_row()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_finance_validate_allocation_share "
        "AFTER INSERT ON finance.movement_allocations "
        "DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION "
        "finance.validate_movement_allocation_share_row()"
    )

    installation = (
        "NULLIF(current_setting('app.current_installation_id', true), '')::uuid"
    )
    residence = "NULLIF(current_setting('app.current_residence_id', true), '')::uuid"
    operator = "NULLIF(current_setting('app.current_operator_id', true), '')::uuid"
    active_membership = (
        "EXISTS (SELECT 1 FROM household.memberships hm "
        "WHERE hm.installation_id = movement_allocation_sets.installation_id "
        "AND hm.residence_id = movement_allocation_sets.residence_id "
        f"AND hm.operator_id = {operator} AND hm.status = 'active')"
    )
    visible_movement = (
        "EXISTS (SELECT 1 FROM finance.movements m "
        "WHERE m.id = movement_allocation_sets.movement_id "
        "AND m.installation_id = movement_allocation_sets.installation_id "
        "AND m.residence_id = movement_allocation_sets.residence_id)"
    )
    owned_target = (
        "EXISTS (SELECT 1 FROM finance.movements m "
        "JOIN finance.accounts a ON a.id = m.account_id "
        "WHERE m.id = movement_allocation_sets.movement_id "
        "AND m.installation_id = movement_allocation_sets.installation_id "
        "AND m.residence_id = movement_allocation_sets.residence_id "
        "AND m.role = 'STANDARD' "
        "AND m.result_effect IN ('INCOME', 'EXPENSE') "
        "AND a.installation_id = movement_allocation_sets.installation_id "
        "AND a.residence_id = movement_allocation_sets.residence_id "
        "AND a.status = 'ACTIVE' "
        f"AND a.owner_operator_id = {operator})"
    )

    op.execute(
        "ALTER TABLE finance.movement_allocation_sets "
        "ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE finance.movement_allocation_sets "
        "FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY finance_allocation_sets_select "
        "ON finance.movement_allocation_sets FOR SELECT USING ("
        f"installation_id = {installation} "
        f"AND residence_id = {residence} "
        f"AND {active_membership} AND {visible_movement})"
    )
    op.execute(
        "CREATE POLICY finance_allocation_sets_insert "
        "ON finance.movement_allocation_sets FOR INSERT WITH CHECK ("
        f"installation_id = {installation} "
        f"AND residence_id = {residence} "
        f"AND created_by_operator_id = {operator} "
        f"AND {active_membership} AND {owned_target})"
    )

    parent_visible = (
        "EXISTS (SELECT 1 FROM finance.movement_allocation_sets s "
        "WHERE s.id = movement_allocations.allocation_set_id "
        "AND s.installation_id = movement_allocations.installation_id "
        "AND s.residence_id = movement_allocations.residence_id "
        "AND s.movement_id = movement_allocations.movement_id)"
    )
    category_visible_active = (
        "EXISTS (SELECT 1 FROM finance.categories c "
        "WHERE c.id = movement_allocations.category_id "
        "AND c.installation_id = movement_allocations.installation_id "
        "AND c.residence_id = movement_allocations.residence_id "
        "AND c.status = 'ACTIVE')"
    )
    op.execute(
        "ALTER TABLE finance.movement_allocations ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE finance.movement_allocations FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY finance_allocations_select "
        "ON finance.movement_allocations FOR SELECT USING ("
        f"{parent_visible})"
    )
    op.execute(
        "CREATE POLICY finance_allocations_insert "
        "ON finance.movement_allocations FOR INSERT WITH CHECK ("
        f"{parent_visible} AND {category_visible_active})"
    )

    op.execute(
        f"REVOKE UPDATE, DELETE ON "
        f"finance.movement_allocation_sets FROM {role}"
    )
    op.execute(
        f"REVOKE UPDATE, DELETE ON "
        f"finance.movement_allocations FROM {role}"
    )
    op.execute(
        f"GRANT SELECT, INSERT ON "
        f"finance.movement_allocation_sets TO {role}"
    )
    op.execute(
        f"GRANT SELECT, INSERT ON "
        f"finance.movement_allocations TO {role}"
    )


def downgrade() -> None:
    role = _quoted_role()
    op.execute(
        f"REVOKE SELECT, INSERT ON "
        f"finance.movement_allocations FROM {role}"
    )
    op.execute(
        f"REVOKE SELECT, INSERT ON "
        f"finance.movement_allocation_sets FROM {role}"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_finance_validate_allocation_share "
        "ON finance.movement_allocations"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_finance_validate_allocation_set "
        "ON finance.movement_allocation_sets"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "finance.validate_movement_allocation_share_row()"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "finance.validate_movement_allocation_set_row()"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "finance.assert_movement_allocation_set(uuid)"
    )
    op.execute("DROP TABLE finance.movement_allocations")
    op.execute("DROP TABLE finance.movement_allocation_sets")
