# mypy: ignore-errors
"""Create monthly category budgets (planning) with forced RLS and CAS versioning.

``finance.budgets`` is planning, never a ledger: no Movement, balance or realized
amount is stored. The runtime role may only INSERT and, for the CAS edit, update
``name``, ``version``, ``updated_at`` and ``updated_by_operator_id``. Lines are
append-only per revision; the current lines are those whose ``revision`` equals
``budgets.version``. Neither table has a DELETE grant.

Revision ID: 0023_monthly_budgets
Revises: 0022_pending_movement_indexes
Create Date: 2026-10-05
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0023_monthly_budgets"
down_revision: str | None = "0022_pending_movement_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")
_NIL_UUID = "00000000-0000-0000-0000-000000000000"


def _quoted_role() -> str:
    role_name = context.config.get_main_option("app_database_user")
    if not _ROLE_PATTERN.fullmatch(role_name):
        raise RuntimeError("invalid app_database_user for migration grants")
    return f'"{role_name}"'


def upgrade() -> None:
    role = _quoted_role()

    op.execute(
        r"""
        CREATE TABLE finance.budgets (
            id uuid PRIMARY KEY,
            installation_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            owner_operator_id uuid NOT NULL,
            visibility_scope varchar(16) NOT NULL,
            name varchar(96) NOT NULL,
            currency varchar(3) NOT NULL,
            period_kind varchar(16) NOT NULL,
            period_start date NOT NULL,
            date_basis varchar(16) NOT NULL,
            version integer NOT NULL,
            idempotency_key uuid NOT NULL,
            request_digest varchar(64) NOT NULL,
            updated_by_operator_id uuid NOT NULL,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            CONSTRAINT ck_finance_budgets_id_uuid4 CHECK (
                id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ),
            CONSTRAINT ck_finance_budgets_idempotency_uuid4 CHECK (
                idempotency_key::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ),
            CONSTRAINT ck_finance_budgets_scope CHECK (
                visibility_scope IN ('PERSONAL', 'HOUSEHOLD')
            ),
            CONSTRAINT ck_finance_budgets_name CHECK (
                length(btrim(name)) BETWEEN 1 AND 96
            ),
            CONSTRAINT ck_finance_budgets_currency CHECK (currency ~ '^[A-Z]{3}$'),
            CONSTRAINT ck_finance_budgets_period_kind CHECK (
                period_kind = 'MONTHLY'
            ),
            CONSTRAINT ck_finance_budgets_period_start CHECK (
                EXTRACT(DAY FROM period_start) = 1
            ),
            CONSTRAINT ck_finance_budgets_date_basis CHECK (
                date_basis IN ('CASH', 'COMPETENCE')
            ),
            CONSTRAINT ck_finance_budgets_version CHECK (version >= 1),
            CONSTRAINT ck_finance_budgets_request_digest CHECK (
                request_digest ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT ck_finance_budgets_timestamps CHECK (updated_at >= created_at),
            CONSTRAINT fk_finance_budgets_residence FOREIGN KEY (
                residence_id, installation_id
            ) REFERENCES household.residences (
                id, installation_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_budgets_owner_membership FOREIGN KEY (
                residence_id, owner_operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_budgets_updater_membership FOREIGN KEY (
                residence_id, updated_by_operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT uq_finance_budgets_scope UNIQUE (
                id, installation_id, residence_id
            ),
            CONSTRAINT uq_finance_budgets_idempotency UNIQUE (
                installation_id, idempotency_key
            )
        )
        """
    )
    # Material uniqueness: one plan per residence/audience/(owner when PERSONAL)/
    # currency/month/date basis, so a month can never carry two competing plans.
    op.execute(
        "CREATE UNIQUE INDEX uq_finance_budgets_material ON finance.budgets ("
        "installation_id, residence_id, visibility_scope, "
        "(CASE WHEN visibility_scope = 'PERSONAL' THEN owner_operator_id "
        f"ELSE '{_NIL_UUID}'::uuid END), "
        "currency, period_start, date_basis)"
    )
    op.execute(
        "CREATE INDEX ix_finance_budgets_period ON finance.budgets "
        "(residence_id, period_start, visibility_scope, id)"
    )

    op.execute(
        r"""
        CREATE TABLE finance.budget_lines (
            budget_id uuid NOT NULL,
            revision integer NOT NULL,
            category_id uuid NOT NULL,
            result_effect varchar(16) NOT NULL,
            installation_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            currency varchar(3) NOT NULL,
            planned_amount numeric(24, 8) NOT NULL,
            created_at timestamptz NOT NULL,
            PRIMARY KEY (budget_id, revision, category_id, result_effect),
            CONSTRAINT ck_finance_budget_lines_revision CHECK (revision >= 1),
            CONSTRAINT ck_finance_budget_lines_effect CHECK (
                result_effect IN ('INCOME', 'EXPENSE')
            ),
            CONSTRAINT ck_finance_budget_lines_currency CHECK (
                currency ~ '^[A-Z]{3}$'
            ),
            CONSTRAINT ck_finance_budget_lines_planned_positive CHECK (
                planned_amount > 0
                AND planned_amount::text NOT IN ('NaN', 'Infinity', '-Infinity')
            ),
            CONSTRAINT fk_finance_budget_lines_budget FOREIGN KEY (
                budget_id, installation_id, residence_id
            ) REFERENCES finance.budgets (
                id, installation_id, residence_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_budget_lines_category FOREIGN KEY (
                category_id
            ) REFERENCES finance.categories (id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_finance_budget_lines_category "
        "ON finance.budget_lines (residence_id, category_id)"
    )

    # Budget row shape: version 1 on insert; only name/version/updated_* move and
    # every update advances the version by exactly one (CAS is also a DB invariant).
    op.execute(
        """
        CREATE FUNCTION finance.enforce_budget_row()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.version IS DISTINCT FROM 1
                   OR NEW.updated_by_operator_id IS DISTINCT FROM NEW.owner_operator_id
                   OR NEW.updated_at IS DISTINCT FROM NEW.created_at
                THEN
                    RAISE EXCEPTION 'a budget starts at version 1 by its owner'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_finance_budgets_initial_state';
                END IF;
                RETURN NEW;
            END IF;

            IF NEW.version IS DISTINCT FROM OLD.version + 1
               OR NEW.updated_at < OLD.updated_at
               OR (to_jsonb(NEW) - 'name' - 'version' - 'updated_at'
                        - 'updated_by_operator_id')
                    IS DISTINCT FROM
                  (to_jsonb(OLD) - 'name' - 'version' - 'updated_at'
                        - 'updated_by_operator_id')
            THEN
                RAISE EXCEPTION 'budget identity is immutable and versions advance by one'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_budgets_immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_finance_enforce_budget_row "
        "BEFORE INSERT OR UPDATE ON finance.budgets "
        "FOR EACH ROW EXECUTE FUNCTION finance.enforce_budget_row()"
    )

    # Line integrity: lines may only be appended to the revision the budget row
    # was written at *in this very transaction*, and only for an eligible category.
    op.execute(
        """
        CREATE FUNCTION finance.validate_budget_line_row()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            budget_row finance.budgets%ROWTYPE;
            category_row finance.categories%ROWTYPE;
        BEGIN
            SELECT b.*
              INTO budget_row
              FROM finance.budgets b
             WHERE b.id = NEW.budget_id;
            IF NOT FOUND
               OR budget_row.version IS DISTINCT FROM NEW.revision
               OR budget_row.updated_at IS DISTINCT FROM transaction_timestamp()
               OR budget_row.currency IS DISTINCT FROM NEW.currency
            THEN
                RAISE EXCEPTION 'budget line does not belong to the current revision'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_budget_lines_revision_current';
            END IF;

            SELECT c.*
              INTO category_row
              FROM finance.categories c
             WHERE c.id = NEW.category_id;
            IF NOT FOUND
               OR category_row.installation_id IS DISTINCT FROM NEW.installation_id
               OR category_row.residence_id IS DISTINCT FROM NEW.residence_id
               OR category_row.status IS DISTINCT FROM 'ACTIVE'
            THEN
                RAISE EXCEPTION 'budget line category is not eligible'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_budget_lines_category';
            END IF;

            IF NOT (
                (budget_row.visibility_scope = 'HOUSEHOLD'
                    AND category_row.visibility_scope = 'HOUSEHOLD')
                OR (budget_row.visibility_scope = 'PERSONAL'
                    AND category_row.visibility_scope = 'PERSONAL'
                    AND category_row.owner_operator_id
                        = budget_row.owner_operator_id)
            ) THEN
                RAISE EXCEPTION 'budget line category audience mismatch'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_budget_lines_audience';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_finance_validate_budget_line "
        "BEFORE INSERT ON finance.budget_lines "
        "FOR EACH ROW EXECUTE FUNCTION finance.validate_budget_line_row()"
    )

    # Commit-time closure: the current revision of every budget written in this
    # transaction must carry 1..100 lines (an empty or oversized plan never commits).
    op.execute(
        """
        CREATE FUNCTION finance.validate_budget_closure()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            line_count integer;
        BEGIN
            SELECT count(*)
              INTO line_count
              FROM finance.budget_lines l
             WHERE l.budget_id = NEW.id
               AND l.revision = NEW.version;
            IF line_count < 1 OR line_count > 100 THEN
                RAISE EXCEPTION 'a budget revision needs between 1 and 100 lines'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_budgets_line_count';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_finance_validate_budget_closure "
        "AFTER INSERT OR UPDATE ON finance.budgets "
        "DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION finance.validate_budget_closure()"
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

    budgets = "budgets"
    budget_scope = (
        f"{budgets}.installation_id = {installation} "
        f"AND {budgets}.residence_id = {residence} "
        f"AND {active_membership(budgets)}"
    )
    budget_owned = f"{budgets}.owner_operator_id = {operator}"

    op.execute("ALTER TABLE finance.budgets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finance.budgets FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY finance_budgets_select ON finance.budgets "
        f"FOR SELECT USING ({budget_scope} "
        f"AND ({budgets}.visibility_scope = 'HOUSEHOLD' OR {budget_owned}))"
    )
    op.execute(
        "CREATE POLICY finance_budgets_insert ON finance.budgets "
        f"FOR INSERT WITH CHECK ({budget_scope} AND {budget_owned} "
        f"AND {budgets}.visibility_scope IN ('PERSONAL', 'HOUSEHOLD') "
        f"AND {budgets}.version = 1 "
        f"AND {budgets}.updated_by_operator_id = {operator})"
    )
    # Read access to a HOUSEHOLD budget never implies write access: only the owner.
    op.execute(
        "CREATE POLICY finance_budgets_update ON finance.budgets "
        f"FOR UPDATE USING ({budget_scope} AND {budget_owned}) "
        f"WITH CHECK ({budget_scope} AND {budget_owned} "
        f"AND {budgets}.updated_by_operator_id = {operator})"
    )

    lines = "budget_lines"
    parent_visible = (
        "EXISTS (SELECT 1 FROM finance.budgets b "
        f"WHERE b.id = {lines}.budget_id "
        f"AND b.installation_id = {lines}.installation_id "
        f"AND b.residence_id = {lines}.residence_id)"
    )
    parent_owned = parent_visible[:-1] + f" AND b.owner_operator_id = {operator})"
    category_visible_active = (
        "EXISTS (SELECT 1 FROM finance.categories c "
        f"WHERE c.id = {lines}.category_id "
        f"AND c.installation_id = {lines}.installation_id "
        f"AND c.residence_id = {lines}.residence_id AND c.status = 'ACTIVE')"
    )
    op.execute("ALTER TABLE finance.budget_lines ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finance.budget_lines FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY finance_budget_lines_select ON finance.budget_lines "
        f"FOR SELECT USING ({parent_visible})"
    )
    op.execute(
        "CREATE POLICY finance_budget_lines_insert ON finance.budget_lines "
        f"FOR INSERT WITH CHECK ({parent_owned} AND {category_visible_active})"
    )

    op.execute(f"GRANT SELECT, INSERT ON finance.budgets TO {role}")
    op.execute(
        "GRANT UPDATE (name, version, updated_at, updated_by_operator_id) "
        f"ON finance.budgets TO {role}"
    )
    op.execute(f"GRANT SELECT, INSERT ON finance.budget_lines TO {role}")


def downgrade() -> None:
    role = _quoted_role()
    op.execute(f"REVOKE SELECT, INSERT ON finance.budget_lines FROM {role}")
    op.execute(
        "REVOKE UPDATE (name, version, updated_at, updated_by_operator_id) "
        f"ON finance.budgets FROM {role}"
    )
    op.execute(f"REVOKE SELECT, INSERT ON finance.budgets FROM {role}")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_finance_validate_budget_closure ON finance.budgets"
    )
    op.execute("DROP FUNCTION IF EXISTS finance.validate_budget_closure()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_finance_validate_budget_line "
        "ON finance.budget_lines"
    )
    op.execute("DROP FUNCTION IF EXISTS finance.validate_budget_line_row()")
    op.execute("DROP TABLE finance.budget_lines")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_finance_enforce_budget_row ON finance.budgets"
    )
    op.execute("DROP FUNCTION IF EXISTS finance.enforce_budget_row()")
    op.execute("DROP TABLE finance.budgets")
