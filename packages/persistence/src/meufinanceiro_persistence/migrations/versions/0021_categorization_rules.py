# mypy: ignore-errors
"""Create deterministic categorization rules and append-only rule provenance.

Rules are semantically immutable: the runtime role may only flip a rule from
ACTIVE to DISABLED. Provenance (one optional origin per first-revision allocation
set) is append-only and never decides which classification is current.

Revision ID: 0021_categorization_rules
Revises: 0020_banking_review_audit_bridge
Create Date: 2026-10-05
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0021_categorization_rules"
down_revision: str | None = "0020_banking_review_audit_bridge"
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
        ALTER TABLE finance.movement_allocation_sets
            ADD CONSTRAINT uq_finance_allocation_sets_origin_scope UNIQUE (
                id, installation_id, residence_id, movement_id
            )
        """
    )

    op.execute(
        r"""
        CREATE TABLE finance.categorization_rules (
            id uuid PRIMARY KEY,
            installation_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            created_by_operator_id uuid NOT NULL,
            account_id uuid,
            result_effect varchar(16),
            description_matcher varchar(16) NOT NULL,
            description_pattern varchar(256) NOT NULL,
            target_category_id uuid NOT NULL,
            priority integer NOT NULL,
            status varchar(16) NOT NULL,
            idempotency_key uuid NOT NULL,
            request_digest varchar(64) NOT NULL,
            created_at timestamptz NOT NULL,
            disabled_at timestamptz,
            disabled_by_operator_id uuid,
            CONSTRAINT ck_finance_cat_rules_id_uuid4 CHECK (
                id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ),
            CONSTRAINT ck_finance_cat_rules_idempotency_uuid4 CHECK (
                idempotency_key::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ),
            CONSTRAINT ck_finance_cat_rules_result_effect CHECK (
                result_effect IS NULL OR result_effect IN ('INCOME', 'EXPENSE')
            ),
            CONSTRAINT ck_finance_cat_rules_matcher CHECK (
                description_matcher IN ('EXACT', 'CONTAINS')
            ),
            CONSTRAINT ck_finance_cat_rules_pattern_length CHECK (
                length(btrim(description_pattern)) BETWEEN 1 AND 256
            ),
            CONSTRAINT ck_finance_cat_rules_priority CHECK (
                priority BETWEEN 1 AND 1000
            ),
            CONSTRAINT ck_finance_cat_rules_status CHECK (
                status IN ('ACTIVE', 'DISABLED')
            ),
            CONSTRAINT ck_finance_cat_rules_disable_state CHECK (
                (status = 'ACTIVE' AND disabled_at IS NULL
                    AND disabled_by_operator_id IS NULL)
                OR (status = 'DISABLED' AND disabled_at IS NOT NULL
                    AND disabled_by_operator_id IS NOT NULL)
            ),
            CONSTRAINT ck_finance_cat_rules_request_digest CHECK (
                request_digest ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT ck_finance_cat_rules_timestamps CHECK (
                disabled_at IS NULL OR disabled_at >= created_at
            ),
            CONSTRAINT fk_finance_cat_rules_residence FOREIGN KEY (
                residence_id, installation_id
            ) REFERENCES household.residences (
                id, installation_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_cat_rules_creator_membership FOREIGN KEY (
                residence_id, created_by_operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_cat_rules_disabler_membership FOREIGN KEY (
                residence_id, disabled_by_operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_cat_rules_account FOREIGN KEY (
                account_id
            ) REFERENCES finance.accounts (id) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_cat_rules_category FOREIGN KEY (
                target_category_id
            ) REFERENCES finance.categories (id) ON DELETE RESTRICT,
            CONSTRAINT uq_finance_cat_rules_scope UNIQUE (
                id, installation_id, residence_id
            ),
            CONSTRAINT uq_finance_cat_rules_idempotency UNIQUE (
                installation_id, idempotency_key
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_finance_cat_rules_scope "
        "ON finance.categorization_rules "
        "(residence_id, status, priority DESC, created_at, id)"
    )
    op.execute(
        "CREATE INDEX ix_finance_cat_rules_category "
        "ON finance.categorization_rules (residence_id, target_category_id)"
    )

    op.execute(
        """
        CREATE TABLE finance.movement_allocation_rule_origins (
            allocation_set_id uuid PRIMARY KEY,
            installation_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            movement_id uuid NOT NULL,
            rule_id uuid NOT NULL,
            created_at timestamptz NOT NULL,
            CONSTRAINT fk_finance_rule_origins_set FOREIGN KEY (
                allocation_set_id, installation_id, residence_id, movement_id
            ) REFERENCES finance.movement_allocation_sets (
                id, installation_id, residence_id, movement_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_rule_origins_rule FOREIGN KEY (
                rule_id, installation_id, residence_id
            ) REFERENCES finance.categorization_rules (
                id, installation_id, residence_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_rule_origins_movement FOREIGN KEY (
                movement_id
            ) REFERENCES finance.movements (id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_finance_rule_origins_rule "
        "ON finance.movement_allocation_rule_origins (residence_id, rule_id)"
    )
    op.execute(
        "CREATE INDEX ix_finance_rule_origins_movement "
        "ON finance.movement_allocation_rule_origins (residence_id, movement_id)"
    )

    # Rule creation: defense in depth for what the store already validates.
    op.execute(
        """
        CREATE FUNCTION finance.validate_categorization_rule_row()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            category_row finance.categories%ROWTYPE;
            account_row finance.accounts%ROWTYPE;
        BEGIN
            SELECT c.*
              INTO category_row
              FROM finance.categories c
             WHERE c.id = NEW.target_category_id;
            IF NOT FOUND
               OR category_row.installation_id IS DISTINCT FROM NEW.installation_id
               OR category_row.residence_id IS DISTINCT FROM NEW.residence_id
               OR category_row.status IS DISTINCT FROM 'ACTIVE'
            THEN
                RAISE EXCEPTION 'categorization rule target category is not eligible'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_cat_rules_target_category';
            END IF;

            IF category_row.visibility_scope <> 'HOUSEHOLD'
               AND category_row.owner_operator_id
                    IS DISTINCT FROM NEW.created_by_operator_id
            THEN
                RAISE EXCEPTION 'categorization rule target category audience mismatch'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_cat_rules_target_audience';
            END IF;

            IF NEW.account_id IS NOT NULL THEN
                SELECT a.*
                  INTO account_row
                  FROM finance.accounts a
                 WHERE a.id = NEW.account_id;
                IF NOT FOUND
                   OR account_row.installation_id IS DISTINCT FROM NEW.installation_id
                   OR account_row.residence_id IS DISTINCT FROM NEW.residence_id
                   OR account_row.status IS DISTINCT FROM 'ACTIVE'
                   OR account_row.owner_operator_id
                        IS DISTINCT FROM NEW.created_by_operator_id
                THEN
                    RAISE EXCEPTION 'categorization rule account is not eligible'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_finance_cat_rules_account';
                END IF;

                IF category_row.visibility_scope <> 'HOUSEHOLD'
                   AND NOT (
                        account_row.visibility_scope = 'PERSONAL'
                        AND category_row.visibility_scope = 'PERSONAL'
                        AND category_row.owner_operator_id
                            = account_row.owner_operator_id
                   )
                THEN
                    RAISE EXCEPTION 'categorization rule category/account audience mismatch'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_finance_cat_rules_account_audience';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_finance_validate_categorization_rule "
        "AFTER INSERT ON finance.categorization_rules "
        "FOR EACH ROW EXECUTE FUNCTION finance.validate_categorization_rule_row()"
    )

    # Semantic immutability: only ACTIVE -> DISABLED is ever a valid UPDATE.
    op.execute(
        """
        CREATE FUNCTION finance.enforce_categorization_rule_immutability()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
            IF OLD.status IS DISTINCT FROM 'ACTIVE'
               OR NEW.status IS DISTINCT FROM 'DISABLED'
               OR (to_jsonb(NEW) - 'status' - 'disabled_at' - 'disabled_by_operator_id')
                    IS DISTINCT FROM
                  (to_jsonb(OLD) - 'status' - 'disabled_at' - 'disabled_by_operator_id')
            THEN
                RAISE EXCEPTION 'categorization rule semantics are immutable'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_cat_rules_immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_finance_categorization_rule_immutable "
        "BEFORE UPDATE ON finance.categorization_rules "
        "FOR EACH ROW EXECUTE FUNCTION "
        "finance.enforce_categorization_rule_immutability()"
    )

    # Provenance integrity. The rule is locked FOR SHARE so a concurrent disable
    # serializes with the application: either the rule was disabled first (this
    # classification is rejected) or the application committed first.
    op.execute(
        """
        CREATE FUNCTION finance.validate_movement_allocation_rule_origin_row()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            set_row finance.movement_allocation_sets%ROWTYPE;
            movement_row finance.movements%ROWTYPE;
            rule_row finance.categorization_rules%ROWTYPE;
            share_row finance.movement_allocations%ROWTYPE;
            share_count integer := 0;
        BEGIN
            SELECT s.*
              INTO set_row
              FROM finance.movement_allocation_sets s
             WHERE s.id = NEW.allocation_set_id;
            IF NOT FOUND
               OR set_row.revision <> 1
               OR set_row.supersedes_id IS NOT NULL
            THEN
                RAISE EXCEPTION 'rule origin requires a first classification'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_rule_origin_first_revision';
            END IF;

            SELECT m.*
              INTO movement_row
              FROM finance.movements m
             WHERE m.id = NEW.movement_id;
            IF NOT FOUND
               OR movement_row.role IS DISTINCT FROM 'STANDARD'
               OR movement_row.result_effect NOT IN ('INCOME', 'EXPENSE')
            THEN
                RAISE EXCEPTION 'rule origin Movement is not eligible'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_rule_origin_movement';
            END IF;

            SELECT r.*
              INTO rule_row
              FROM finance.categorization_rules r
             WHERE r.id = NEW.rule_id
               AND r.installation_id = NEW.installation_id
               AND r.residence_id = NEW.residence_id
               AND r.status = 'ACTIVE'
               FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'rule origin rule is not active'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_rule_origin_rule_active';
            END IF;

            IF (rule_row.account_id IS NOT NULL
                    AND rule_row.account_id IS DISTINCT FROM movement_row.account_id)
               OR (rule_row.result_effect IS NOT NULL
                    AND rule_row.result_effect
                        IS DISTINCT FROM movement_row.result_effect)
            THEN
                RAISE EXCEPTION 'rule origin conditions do not hold'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_rule_origin_conditions';
            END IF;

            FOR share_row IN
                SELECT a.*
                  FROM finance.movement_allocations a
                 WHERE a.allocation_set_id = NEW.allocation_set_id
            LOOP
                share_count := share_count + 1;
                IF share_row.category_id IS DISTINCT FROM rule_row.target_category_id
                   OR share_row.amount IS DISTINCT FROM movement_row.amount
                   OR share_row.currency IS DISTINCT FROM movement_row.currency
                THEN
                    RAISE EXCEPTION 'rule origin allocation does not match the rule'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_finance_rule_origin_allocation';
                END IF;
            END LOOP;
            IF share_count <> 1 THEN
                RAISE EXCEPTION 'rule origin requires a single allocation share'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_rule_origin_allocation';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_finance_validate_rule_origin "
        "AFTER INSERT ON finance.movement_allocation_rule_origins "
        "FOR EACH ROW EXECUTE FUNCTION "
        "finance.validate_movement_allocation_rule_origin_row()"
    )

    installation = (
        "NULLIF(current_setting('app.current_installation_id', true), '')::uuid"
    )
    residence = "NULLIF(current_setting('app.current_residence_id', true), '')::uuid"
    operator = "NULLIF(current_setting('app.current_operator_id', true), '')::uuid"

    def active_membership(table: str) -> str:
        return (
            "EXISTS (SELECT 1 FROM household.memberships hm "
            f"WHERE hm.installation_id = {table}.installation_id "
            f"AND hm.residence_id = {table}.residence_id "
            f"AND hm.operator_id = {operator} AND hm.status = 'active')"
        )

    rules = "categorization_rules"
    category_visible = (
        "EXISTS (SELECT 1 FROM finance.categories c "
        f"WHERE c.id = {rules}.target_category_id "
        f"AND c.installation_id = {rules}.installation_id "
        f"AND c.residence_id = {rules}.residence_id)"
    )
    category_visible_active = category_visible[:-1] + " AND c.status = 'ACTIVE')"
    account_visible = (
        f"({rules}.account_id IS NULL OR EXISTS (SELECT 1 FROM finance.accounts a "
        f"WHERE a.id = {rules}.account_id "
        f"AND a.installation_id = {rules}.installation_id "
        f"AND a.residence_id = {rules}.residence_id))"
    )
    account_owned_active = (
        f"({rules}.account_id IS NULL OR EXISTS (SELECT 1 FROM finance.accounts a "
        f"WHERE a.id = {rules}.account_id "
        f"AND a.installation_id = {rules}.installation_id "
        f"AND a.residence_id = {rules}.residence_id "
        f"AND a.status = 'ACTIVE' AND a.owner_operator_id = {operator}))"
    )
    rule_scope = (
        f"{rules}.installation_id = {installation} "
        f"AND {rules}.residence_id = {residence} "
        f"AND {active_membership(rules)}"
    )

    op.execute("ALTER TABLE finance.categorization_rules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finance.categorization_rules FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY finance_cat_rules_select ON finance.categorization_rules "
        f"FOR SELECT USING ({rule_scope} "
        f"AND {category_visible} AND {account_visible})"
    )
    op.execute(
        "CREATE POLICY finance_cat_rules_insert ON finance.categorization_rules "
        f"FOR INSERT WITH CHECK ({rule_scope} "
        f"AND {rules}.created_by_operator_id = {operator} "
        f"AND {rules}.status = 'ACTIVE' AND {rules}.disabled_at IS NULL "
        f"AND {category_visible_active} AND {account_owned_active})"
    )
    # USING stays visibility-only so any member that may *apply* a visible rule can
    # also take the row lock used by provenance validation; only the creator can
    # satisfy WITH CHECK, hence only the creator can disable.
    op.execute(
        "CREATE POLICY finance_cat_rules_update ON finance.categorization_rules "
        f"FOR UPDATE USING ({rule_scope} "
        f"AND {category_visible} AND {account_visible}) "
        f"WITH CHECK ({rule_scope} "
        f"AND {rules}.created_by_operator_id = {operator} "
        f"AND {rules}.disabled_by_operator_id = {operator} "
        f"AND {rules}.status = 'DISABLED')"
    )

    origins = "movement_allocation_rule_origins"
    parent_visible = (
        "EXISTS (SELECT 1 FROM finance.movement_allocation_sets s "
        f"WHERE s.id = {origins}.allocation_set_id "
        f"AND s.installation_id = {origins}.installation_id "
        f"AND s.residence_id = {origins}.residence_id "
        f"AND s.movement_id = {origins}.movement_id)"
    )
    parent_created_by_operator = parent_visible[:-1] + (
        f" AND s.created_by_operator_id = {operator})"
    )
    rule_visible = (
        "EXISTS (SELECT 1 FROM finance.categorization_rules r "
        f"WHERE r.id = {origins}.rule_id "
        f"AND r.installation_id = {origins}.installation_id "
        f"AND r.residence_id = {origins}.residence_id)"
    )
    op.execute(
        "ALTER TABLE finance.movement_allocation_rule_origins ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE finance.movement_allocation_rule_origins FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY finance_rule_origins_select "
        "ON finance.movement_allocation_rule_origins "
        f"FOR SELECT USING ({parent_visible})"
    )
    op.execute(
        "CREATE POLICY finance_rule_origins_insert "
        "ON finance.movement_allocation_rule_origins "
        f"FOR INSERT WITH CHECK ({parent_created_by_operator} "
        f"AND {rule_visible})"
    )

    op.execute(f"GRANT SELECT, INSERT ON finance.categorization_rules TO {role}")
    op.execute(
        "GRANT UPDATE (status, disabled_at, disabled_by_operator_id) "
        f"ON finance.categorization_rules TO {role}"
    )
    op.execute(
        f"GRANT SELECT, INSERT ON finance.movement_allocation_rule_origins TO {role}"
    )


def downgrade() -> None:
    role = _quoted_role()
    op.execute(
        f"REVOKE SELECT, INSERT ON finance.movement_allocation_rule_origins FROM {role}"
    )
    op.execute(
        "REVOKE UPDATE (status, disabled_at, disabled_by_operator_id) "
        f"ON finance.categorization_rules FROM {role}"
    )
    op.execute(f"REVOKE SELECT, INSERT ON finance.categorization_rules FROM {role}")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_finance_validate_rule_origin "
        "ON finance.movement_allocation_rule_origins"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS finance.validate_movement_allocation_rule_origin_row()"
    )
    op.execute("DROP TABLE finance.movement_allocation_rule_origins")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_finance_categorization_rule_immutable "
        "ON finance.categorization_rules"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS finance.enforce_categorization_rule_immutability()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_finance_validate_categorization_rule "
        "ON finance.categorization_rules"
    )
    op.execute("DROP FUNCTION IF EXISTS finance.validate_categorization_rule_row()")
    op.execute("DROP TABLE finance.categorization_rules")
    op.execute(
        "ALTER TABLE finance.movement_allocation_sets "
        "DROP CONSTRAINT uq_finance_allocation_sets_origin_scope"
    )
