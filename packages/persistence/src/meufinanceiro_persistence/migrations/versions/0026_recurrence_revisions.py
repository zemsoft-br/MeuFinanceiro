# mypy: ignore-errors
"""Keep an append-only, database-authored history of every recurrence revision.

``finance.recurrences`` is updated in place and only its CAS ``version`` advanced, so a
superseded description, expected amount, day, end date or status was lost unless an
occurrence happened to snapshot it. ``finance.recurrence_revisions`` stores one
immutable row per ``(recurrence_id, version)`` with the full rule state, the actor and
the instant.

The row is written by an AFTER INSERT OR UPDATE trigger on the rule, in the same
statement and transaction as the rule change, from the very row being stored. A valid
rule write therefore cannot exist without its revision, a rollback removes both, and a
no-op or a stale CAS (which never updates the rule) writes nothing. The runtime role
may only SELECT and INSERT revisions, and the insert policy only admits a write made
from inside a trigger, so the application cannot forge, skip or alter history.

Revision ID: 0026_recurrence_revisions
Revises: 0025_monthly_recurrences
Create Date: 2026-10-07
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0026_recurrence_revisions"
down_revision: str | None = "0025_monthly_recurrences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")

_UUID4 = "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'"
_COLUMNS = (
    "recurrence_id, version, installation_id, residence_id, account_id, "
    "owner_operator_id, description, result_effect, currency, expected_amount, "
    "frequency, start_date, day_of_month, end_date, status, actor_operator_id, "
    "recorded_at"
)
_RULE_VALUES = (
    "id, version, installation_id, residence_id, account_id, owner_operator_id, "
    "description, result_effect, currency, expected_amount, frequency, start_date, "
    "day_of_month, end_date, status, updated_by_operator_id, updated_at"
)


def _quoted_role() -> str:
    role_name = context.config.get_main_option("app_database_user")
    if not _ROLE_PATTERN.fullmatch(role_name):
        raise RuntimeError("invalid app_database_user for migration grants")
    return f'"{role_name}"'


def upgrade() -> None:
    role = _quoted_role()

    op.execute(
        f"""
        CREATE TABLE finance.recurrence_revisions (
            recurrence_id uuid NOT NULL,
            version integer NOT NULL,
            installation_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            account_id uuid NOT NULL,
            owner_operator_id uuid NOT NULL,
            description varchar(256) NOT NULL,
            result_effect varchar(16) NOT NULL,
            currency varchar(3) NOT NULL,
            expected_amount numeric(24, 8) NOT NULL,
            frequency varchar(16) NOT NULL,
            start_date date NOT NULL,
            day_of_month integer NOT NULL,
            end_date date,
            status varchar(16) NOT NULL,
            actor_operator_id uuid NOT NULL,
            recorded_at timestamptz NOT NULL,
            CONSTRAINT pk_finance_recurrence_revisions PRIMARY KEY (
                recurrence_id, version
            ),
            CONSTRAINT ck_finance_recurrence_revisions_version CHECK (version >= 1),
            CONSTRAINT ck_finance_recurrence_revisions_recurrence_uuid4 CHECK (
                recurrence_id::text ~ {_UUID4}
            ),
            CONSTRAINT ck_finance_recurrence_revisions_description CHECK (
                length(btrim(description)) BETWEEN 1 AND 256
                AND description !~ '[\\x01-\\x1f\\x7f]'
            ),
            CONSTRAINT ck_finance_recurrence_revisions_effect CHECK (
                result_effect IN ('INCOME', 'EXPENSE')
            ),
            CONSTRAINT ck_finance_recurrence_revisions_currency CHECK (
                currency ~ '^[A-Z]{{3}}$'
            ),
            CONSTRAINT ck_finance_recurrence_revisions_expected_positive CHECK (
                expected_amount > 0
                AND expected_amount::text NOT IN ('NaN', 'Infinity', '-Infinity')
            ),
            CONSTRAINT ck_finance_recurrence_revisions_frequency CHECK (
                frequency = 'MONTHLY'
            ),
            CONSTRAINT ck_finance_recurrence_revisions_day CHECK (
                day_of_month BETWEEN 1 AND 31
            ),
            CONSTRAINT ck_finance_recurrence_revisions_dates CHECK (
                end_date IS NULL OR end_date >= start_date
            ),
            CONSTRAINT ck_finance_recurrence_revisions_status CHECK (
                status IN ('ACTIVE', 'PAUSED')
            ),
            CONSTRAINT fk_finance_recurrence_revisions_rule FOREIGN KEY (
                recurrence_id, installation_id, residence_id
            ) REFERENCES finance.recurrences (
                id, installation_id, residence_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_recurrence_revisions_account FOREIGN KEY (
                account_id, installation_id, residence_id, currency
            ) REFERENCES finance.accounts (
                id, installation_id, residence_id, currency
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_recurrence_revisions_owner_membership FOREIGN KEY (
                residence_id, owner_operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_recurrence_revisions_actor_membership FOREIGN KEY (
                residence_id, actor_operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_finance_recurrence_revisions_residence "
        "ON finance.recurrence_revisions (residence_id, recurrence_id)"
    )

    installation = (
        "NULLIF(current_setting('app.current_installation_id', true), '')::uuid"
    )
    residence = "NULLIF(current_setting('app.current_residence_id', true), '')::uuid"
    operator = "NULLIF(current_setting('app.current_operator_id', true), '')::uuid"
    rev = "recurrence_revisions"
    scope = (
        f"{rev}.installation_id = {installation} "
        f"AND {rev}.residence_id = {residence} "
        "AND EXISTS (SELECT 1 FROM household.memberships hm "
        f"WHERE hm.installation_id = {rev}.installation_id "
        f"AND hm.residence_id = {rev}.residence_id "
        f"AND hm.operator_id = {operator} AND hm.status = 'active')"
    )
    # Both subqueries are filtered by the row policies of the rule and of the account,
    # so a revision is exactly as visible as the rule it belongs to and the account it
    # was written for (PERSONAL / SHARED / HOUSEHOLD included).
    parent_visible = (
        "EXISTS (SELECT 1 FROM finance.recurrences r "
        f"WHERE r.id = {rev}.recurrence_id "
        f"AND r.installation_id = {rev}.installation_id "
        f"AND r.residence_id = {rev}.residence_id)"
    )
    account_visible = (
        "EXISTS (SELECT 1 FROM finance.accounts a "
        f"WHERE a.id = {rev}.account_id "
        f"AND a.installation_id = {rev}.installation_id "
        f"AND a.residence_id = {rev}.residence_id "
        f"AND a.currency = {rev}.currency)"
    )
    parent_owned = parent_visible[:-1] + f" AND r.owner_operator_id = {operator})"

    # Backfill: a rule that already exists keeps its *current* revision as the first
    # recorded one (earlier states were never stored and cannot be reconstructed).
    # The owner is subject to RLS when forced, so lift FORCE only around the copy.
    op.execute("ALTER TABLE finance.recurrences NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finance.recurrence_revisions NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"INSERT INTO finance.recurrence_revisions ({_COLUMNS}) "
        f"SELECT {_RULE_VALUES} FROM finance.recurrences"
    )
    op.execute("ALTER TABLE finance.recurrence_revisions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finance.recurrence_revisions FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finance.recurrences FORCE ROW LEVEL SECURITY")

    op.execute(
        "CREATE POLICY finance_recurrence_revisions_select "
        "ON finance.recurrence_revisions "
        f"FOR SELECT USING ({scope} AND {parent_visible} AND {account_visible})"
    )
    # Only a trigger may write a revision: a client statement runs at trigger depth 0.
    op.execute(
        "CREATE POLICY finance_recurrence_revisions_insert "
        "ON finance.recurrence_revisions "
        f"FOR INSERT WITH CHECK (pg_catalog.pg_trigger_depth() > 0 AND {scope} "
        f"AND {parent_owned} AND {rev}.owner_operator_id = {operator} "
        f"AND {rev}.actor_operator_id = {operator})"
    )

    # The revision must be the rule exactly as stored now, and the next one in line.
    op.execute(
        """
        CREATE FUNCTION finance.validate_recurrence_revision_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            rule_row finance.recurrences%ROWTYPE;
        BEGIN
            SELECT r.*
              INTO rule_row
              FROM finance.recurrences r
             WHERE r.id = NEW.recurrence_id;
            IF NOT FOUND
               OR rule_row.version IS DISTINCT FROM NEW.version
               OR rule_row.installation_id IS DISTINCT FROM NEW.installation_id
               OR rule_row.residence_id IS DISTINCT FROM NEW.residence_id
               OR rule_row.account_id IS DISTINCT FROM NEW.account_id
               OR rule_row.owner_operator_id IS DISTINCT FROM NEW.owner_operator_id
               OR rule_row.description IS DISTINCT FROM NEW.description
               OR rule_row.result_effect IS DISTINCT FROM NEW.result_effect
               OR rule_row.currency IS DISTINCT FROM NEW.currency
               OR rule_row.expected_amount IS DISTINCT FROM NEW.expected_amount
               OR rule_row.frequency IS DISTINCT FROM NEW.frequency
               OR rule_row.start_date IS DISTINCT FROM NEW.start_date
               OR rule_row.day_of_month IS DISTINCT FROM NEW.day_of_month
               OR rule_row.end_date IS DISTINCT FROM NEW.end_date
               OR rule_row.status IS DISTINCT FROM NEW.status
               OR rule_row.updated_by_operator_id
                    IS DISTINCT FROM NEW.actor_operator_id
               OR rule_row.updated_at IS DISTINCT FROM NEW.recorded_at
            THEN
                RAISE EXCEPTION 'a revision must record the recurrence as stored'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_recurrence_revisions_snapshot';
            END IF;

            IF NEW.version > 1
               AND NOT EXISTS (
                    SELECT 1
                      FROM finance.recurrence_revisions p
                     WHERE p.recurrence_id = NEW.recurrence_id
                       AND p.version = NEW.version - 1
               )
               AND EXISTS (
                    SELECT 1
                      FROM finance.recurrence_revisions p
                     WHERE p.recurrence_id = NEW.recurrence_id
               )
            THEN
                RAISE EXCEPTION 'recurrence revisions must not skip a version'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_recurrence_revisions_sequence';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_finance_validate_recurrence_revision_insert "
        "BEFORE INSERT ON finance.recurrence_revisions "
        "FOR EACH ROW EXECUTE FUNCTION "
        "finance.validate_recurrence_revision_insert()"
    )

    op.execute(
        """
        CREATE FUNCTION finance.reject_recurrence_revision_update()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
            RAISE EXCEPTION 'recurrence revisions are append-only'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'ck_finance_recurrence_revisions_immutable';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_finance_reject_recurrence_revision_update "
        "BEFORE UPDATE ON finance.recurrence_revisions "
        "FOR EACH ROW EXECUTE FUNCTION finance.reject_recurrence_revision_update()"
    )

    # The writer: one revision per stored rule state, from the stored row itself.
    op.execute(
        f"""
        CREATE FUNCTION finance.record_recurrence_revision()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
            INSERT INTO finance.recurrence_revisions ({_COLUMNS})
            VALUES (
                NEW.id, NEW.version, NEW.installation_id, NEW.residence_id,
                NEW.account_id, NEW.owner_operator_id, NEW.description,
                NEW.result_effect, NEW.currency, NEW.expected_amount, NEW.frequency,
                NEW.start_date, NEW.day_of_month, NEW.end_date, NEW.status,
                NEW.updated_by_operator_id, NEW.updated_at
            );
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_finance_record_recurrence_revision "
        "AFTER INSERT OR UPDATE ON finance.recurrences "
        "FOR EACH ROW EXECUTE FUNCTION finance.record_recurrence_revision()"
    )

    # No UPDATE, DELETE or TRUNCATE for the runtime: history is append-only.
    op.execute(f"GRANT SELECT, INSERT ON finance.recurrence_revisions TO {role}")


def downgrade() -> None:
    role = _quoted_role()
    op.execute(f"REVOKE SELECT, INSERT ON finance.recurrence_revisions FROM {role}")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_finance_record_recurrence_revision "
        "ON finance.recurrences"
    )
    op.execute("DROP FUNCTION IF EXISTS finance.record_recurrence_revision()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_finance_reject_recurrence_revision_update "
        "ON finance.recurrence_revisions"
    )
    op.execute("DROP FUNCTION IF EXISTS finance.reject_recurrence_revision_update()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_finance_validate_recurrence_revision_insert "
        "ON finance.recurrence_revisions"
    )
    op.execute("DROP FUNCTION IF EXISTS finance.validate_recurrence_revision_insert()")
    op.execute("DROP TABLE finance.recurrence_revisions")
