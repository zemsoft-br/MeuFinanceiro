# mypy: ignore-errors
"""Create manual monthly recurrences and their occurrences (planning, not a ledger).

``finance.recurrences`` is the rule (the model) and carries the CAS ``version``;
``finance.recurrence_occurrences`` is one persisted instance per rule and month with
the snapshot of the revision that made it. Neither table stores a balance, and no
column of ``finance.movements`` changes: an occurrence points to its Movement only
when the user explicitly realizes it, in the very transaction that writes it.

The runtime role may INSERT and SELECT both tables, update the CAS columns of a rule
and the transition columns of a PENDING occurrence. Neither table has a DELETE grant.

Revision ID: 0025_monthly_recurrences
Revises: 0024_budget_realization_indexes
Create Date: 2026-10-06
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0025_monthly_recurrences"
down_revision: str | None = "0024_budget_realization_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")

_UUID4 = "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'"
_RULE_MUTABLE = (
    "description",
    "expected_amount",
    "day_of_month",
    "end_date",
    "status",
    "version",
    "updated_at",
    "updated_by_operator_id",
)
_OCCURRENCE_MUTABLE = (
    "status",
    "updated_at",
    "movement_id",
    "realization_idempotency_key",
    "realization_request_digest",
    "realized_at",
    "realized_by_operator_id",
    "skipped_at",
    "superseded_at",
)


def _quoted_role() -> str:
    role_name = context.config.get_main_option("app_database_user")
    if not _ROLE_PATTERN.fullmatch(role_name):
        raise RuntimeError("invalid app_database_user for migration grants")
    return f'"{role_name}"'


def _array(names: tuple[str, ...]) -> str:
    return "ARRAY[" + ", ".join(f"'{name}'" for name in names) + "]"


def upgrade() -> None:
    role = _quoted_role()

    op.execute(
        f"""
        CREATE TABLE finance.recurrences (
            id uuid PRIMARY KEY,
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
            version integer NOT NULL,
            idempotency_key uuid NOT NULL,
            request_digest varchar(64) NOT NULL,
            updated_by_operator_id uuid NOT NULL,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            CONSTRAINT ck_finance_recurrences_id_uuid4 CHECK (id::text ~ {_UUID4}),
            CONSTRAINT ck_finance_recurrences_idempotency_uuid4 CHECK (
                idempotency_key::text ~ {_UUID4}
            ),
            CONSTRAINT ck_finance_recurrences_description CHECK (
                length(btrim(description)) BETWEEN 1 AND 256
                AND description !~ '[\\x01-\\x1f\\x7f]'
            ),
            CONSTRAINT ck_finance_recurrences_effect CHECK (
                result_effect IN ('INCOME', 'EXPENSE')
            ),
            CONSTRAINT ck_finance_recurrences_currency CHECK (currency ~ '^[A-Z]{{3}}$'),
            CONSTRAINT ck_finance_recurrences_expected_positive CHECK (
                expected_amount > 0
                AND expected_amount::text NOT IN ('NaN', 'Infinity', '-Infinity')
            ),
            CONSTRAINT ck_finance_recurrences_frequency CHECK (frequency = 'MONTHLY'),
            CONSTRAINT ck_finance_recurrences_day CHECK (day_of_month BETWEEN 1 AND 31),
            CONSTRAINT ck_finance_recurrences_dates CHECK (
                end_date IS NULL OR end_date >= start_date
            ),
            CONSTRAINT ck_finance_recurrences_status CHECK (
                status IN ('ACTIVE', 'PAUSED')
            ),
            CONSTRAINT ck_finance_recurrences_version CHECK (version >= 1),
            CONSTRAINT ck_finance_recurrences_request_digest CHECK (
                request_digest ~ '^[0-9a-f]{{64}}$'
            ),
            CONSTRAINT ck_finance_recurrences_timestamps CHECK (
                updated_at >= created_at
            ),
            CONSTRAINT fk_finance_recurrences_residence FOREIGN KEY (
                residence_id, installation_id
            ) REFERENCES household.residences (
                id, installation_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_recurrences_account FOREIGN KEY (
                account_id, installation_id, residence_id, currency
            ) REFERENCES finance.accounts (
                id, installation_id, residence_id, currency
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_recurrences_owner_membership FOREIGN KEY (
                residence_id, owner_operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_recurrences_updater_membership FOREIGN KEY (
                residence_id, updated_by_operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT uq_finance_recurrences_scope UNIQUE (
                id, installation_id, residence_id
            ),
            CONSTRAINT uq_finance_recurrences_idempotency UNIQUE (
                installation_id, idempotency_key
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_finance_recurrences_residence "
        "ON finance.recurrences (residence_id, created_at, id)"
    )
    op.execute(
        "CREATE INDEX ix_finance_recurrences_account "
        "ON finance.recurrences (residence_id, account_id)"
    )

    op.execute(
        f"""
        CREATE TABLE finance.recurrence_occurrences (
            id uuid PRIMARY KEY,
            installation_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            recurrence_id uuid NOT NULL,
            account_id uuid NOT NULL,
            owner_operator_id uuid NOT NULL,
            period_start date NOT NULL,
            scheduled_date date NOT NULL,
            rule_version integer NOT NULL,
            result_effect varchar(16) NOT NULL,
            currency varchar(3) NOT NULL,
            expected_amount numeric(24, 8) NOT NULL,
            description varchar(256) NOT NULL,
            status varchar(16) NOT NULL,
            movement_id uuid,
            realization_idempotency_key uuid,
            realization_request_digest varchar(64),
            realized_at timestamptz,
            realized_by_operator_id uuid,
            skipped_at timestamptz,
            superseded_at timestamptz,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            CONSTRAINT ck_finance_recurrence_occurrences_id_uuid4 CHECK (
                id::text ~ {_UUID4}
            ),
            CONSTRAINT ck_finance_recurrence_occurrences_realization_key_uuid4 CHECK (
                realization_idempotency_key IS NULL
                OR realization_idempotency_key::text ~ {_UUID4}
            ),
            CONSTRAINT ck_finance_recurrence_occurrences_period CHECK (
                EXTRACT(DAY FROM period_start) = 1
                AND date_trunc('month', scheduled_date)::date = period_start
            ),
            CONSTRAINT ck_finance_recurrence_occurrences_rule_version CHECK (
                rule_version >= 1
            ),
            CONSTRAINT ck_finance_recurrence_occurrences_effect CHECK (
                result_effect IN ('INCOME', 'EXPENSE')
            ),
            CONSTRAINT ck_finance_recurrence_occurrences_currency CHECK (
                currency ~ '^[A-Z]{{3}}$'
            ),
            CONSTRAINT ck_finance_recurrence_occurrences_expected_positive CHECK (
                expected_amount > 0
                AND expected_amount::text NOT IN ('NaN', 'Infinity', '-Infinity')
            ),
            CONSTRAINT ck_finance_recurrence_occurrences_description CHECK (
                length(btrim(description)) BETWEEN 1 AND 256
                AND description !~ '[\\x01-\\x1f\\x7f]'
            ),
            CONSTRAINT ck_finance_recurrence_occurrences_status CHECK (
                status IN ('PENDING', 'REALIZED', 'SKIPPED', 'SUPERSEDED')
            ),
            CONSTRAINT ck_finance_recurrence_occurrences_realization_shape CHECK (
                (status = 'REALIZED' AND movement_id IS NOT NULL
                    AND realization_idempotency_key IS NOT NULL
                    AND realization_request_digest ~ '^[0-9a-f]{{64}}$'
                    AND realized_at IS NOT NULL
                    AND realized_by_operator_id IS NOT NULL)
                OR (status <> 'REALIZED' AND movement_id IS NULL
                    AND realization_idempotency_key IS NULL
                    AND realization_request_digest IS NULL
                    AND realized_at IS NULL
                    AND realized_by_operator_id IS NULL)
            ),
            CONSTRAINT ck_finance_recurrence_occurrences_terminal_marks CHECK (
                (status = 'SKIPPED') = (skipped_at IS NOT NULL)
                AND (status = 'SUPERSEDED') = (superseded_at IS NOT NULL)
            ),
            CONSTRAINT ck_finance_recurrence_occurrences_timestamps CHECK (
                updated_at >= created_at
            ),
            CONSTRAINT fk_finance_recurrence_occurrences_rule FOREIGN KEY (
                recurrence_id, installation_id, residence_id
            ) REFERENCES finance.recurrences (
                id, installation_id, residence_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_recurrence_occurrences_account FOREIGN KEY (
                account_id, installation_id, residence_id, currency
            ) REFERENCES finance.accounts (
                id, installation_id, residence_id, currency
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_recurrence_occurrences_movement FOREIGN KEY (
                movement_id
            ) REFERENCES finance.movements (id) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_recurrence_occurrences_owner_membership FOREIGN KEY (
                residence_id, owner_operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_recurrence_occurrences_realizer_membership FOREIGN KEY (
                residence_id, realized_by_operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT uq_finance_recurrence_occurrences_realization_key UNIQUE (
                installation_id, realization_idempotency_key
            ),
            CONSTRAINT uq_finance_recurrence_occurrences_movement UNIQUE (movement_id)
        )
        """
    )
    # One live occurrence per rule and month. SUPERSEDED rows are history and may
    # coexist with the replacement a later generation writes for the same month.
    op.execute(
        "CREATE UNIQUE INDEX uq_finance_recurrence_occurrences_month "
        "ON finance.recurrence_occurrences (recurrence_id, period_start) "
        "WHERE status <> 'SUPERSEDED'"
    )
    op.execute(
        "CREATE INDEX ix_finance_recurrence_occurrences_period "
        "ON finance.recurrence_occurrences (residence_id, period_start, recurrence_id)"
    )
    op.execute(
        "CREATE INDEX ix_finance_recurrence_occurrences_rule "
        "ON finance.recurrence_occurrences (recurrence_id, period_start, created_at)"
    )
    op.execute(
        "CREATE INDEX ix_finance_recurrence_occurrences_pending "
        "ON finance.recurrence_occurrences (recurrence_id, scheduled_date) "
        "WHERE status = 'PENDING'"
    )

    # Rule row shape: version 1, ACTIVE and owned by the account owner on insert;
    # only the CAS columns move and every update advances the version by one.
    op.execute(
        f"""
        CREATE FUNCTION finance.enforce_recurrence_row()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            account_row finance.accounts%ROWTYPE;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                SELECT a.*
                  INTO account_row
                  FROM finance.accounts a
                 WHERE a.id = NEW.account_id;
                IF NEW.version IS DISTINCT FROM 1
                   OR NEW.status IS DISTINCT FROM 'ACTIVE'
                   OR NEW.updated_by_operator_id IS DISTINCT FROM NEW.owner_operator_id
                   OR NEW.updated_at IS DISTINCT FROM NEW.created_at
                   OR NOT FOUND
                   OR account_row.owner_operator_id IS DISTINCT FROM NEW.owner_operator_id
                   OR account_row.status IS DISTINCT FROM 'ACTIVE'
                THEN
                    RAISE EXCEPTION 'a recurrence starts ACTIVE at version 1 on its owner active account'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_finance_recurrences_initial_state';
                END IF;
                RETURN NEW;
            END IF;

            IF NEW.version IS DISTINCT FROM OLD.version + 1
               OR NEW.updated_at < OLD.updated_at
               OR (to_jsonb(NEW) - {_array(_RULE_MUTABLE)})
                    IS DISTINCT FROM
                  (to_jsonb(OLD) - {_array(_RULE_MUTABLE)})
            THEN
                RAISE EXCEPTION 'recurrence identity is immutable and versions advance by one'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_recurrences_immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_finance_enforce_recurrence_row "
        "BEFORE INSERT OR UPDATE ON finance.recurrences "
        "FOR EACH ROW EXECUTE FUNCTION finance.enforce_recurrence_row()"
    )

    # Occurrence insert: a copy of the rule's *current* revision, only for an ACTIVE
    # rule and a date the monthly calendar produces inside [start, end].
    op.execute(
        """
        CREATE FUNCTION finance.validate_recurrence_occurrence_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            rule_row finance.recurrences%ROWTYPE;
            account_status text;
            last_day integer;
        BEGIN
            SELECT r.*
              INTO rule_row
              FROM finance.recurrences r
             WHERE r.id = NEW.recurrence_id;
            IF NOT FOUND
               OR rule_row.installation_id IS DISTINCT FROM NEW.installation_id
               OR rule_row.residence_id IS DISTINCT FROM NEW.residence_id
               OR rule_row.status IS DISTINCT FROM 'ACTIVE'
               OR rule_row.account_id IS DISTINCT FROM NEW.account_id
               OR rule_row.owner_operator_id IS DISTINCT FROM NEW.owner_operator_id
               OR rule_row.version IS DISTINCT FROM NEW.rule_version
               OR rule_row.result_effect IS DISTINCT FROM NEW.result_effect
               OR rule_row.currency IS DISTINCT FROM NEW.currency
               OR rule_row.expected_amount IS DISTINCT FROM NEW.expected_amount
               OR rule_row.description IS DISTINCT FROM NEW.description
            THEN
                RAISE EXCEPTION 'occurrence does not snapshot an active recurrence revision'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_recurrence_occurrences_snapshot';
            END IF;

            last_day := EXTRACT(DAY FROM (
                NEW.period_start + INTERVAL '1 month' - INTERVAL '1 day'
            ))::integer;
            IF NEW.status IS DISTINCT FROM 'PENDING'
               OR NEW.scheduled_date IS DISTINCT FROM make_date(
                    EXTRACT(YEAR FROM NEW.period_start)::integer,
                    EXTRACT(MONTH FROM NEW.period_start)::integer,
                    LEAST(rule_row.day_of_month, last_day)
               )
               OR NEW.scheduled_date < rule_row.start_date
               OR (rule_row.end_date IS NOT NULL
                   AND NEW.scheduled_date > rule_row.end_date)
               OR NEW.updated_at IS DISTINCT FROM NEW.created_at
            THEN
                RAISE EXCEPTION 'occurrence is not a due PENDING month of its recurrence'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_recurrence_occurrences_schedule';
            END IF;

            SELECT a.status
              INTO account_status
              FROM finance.accounts a
             WHERE a.id = NEW.account_id;
            IF account_status IS DISTINCT FROM 'ACTIVE' THEN
                RAISE EXCEPTION 'occurrence account is not active'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_recurrence_occurrences_account';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_finance_validate_recurrence_occurrence_insert "
        "BEFORE INSERT ON finance.recurrence_occurrences "
        "FOR EACH ROW EXECUTE FUNCTION "
        "finance.validate_recurrence_occurrence_insert()"
    )

    # Occurrence transitions: only PENDING moves, only to REALIZED / SKIPPED /
    # SUPERSEDED, and only the transition columns change. REALIZED, SKIPPED and
    # SUPERSEDED are immutable. A realization must point at a Movement written in
    # this very transaction for the same account, effect and currency.
    op.execute(
        f"""
        CREATE FUNCTION finance.enforce_recurrence_occurrence_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            movement_row finance.movements%ROWTYPE;
        BEGIN
            IF OLD.status IS DISTINCT FROM 'PENDING'
               OR NEW.status IS NOT DISTINCT FROM OLD.status
               OR NEW.updated_at < OLD.updated_at
               OR (to_jsonb(NEW) - {_array(_OCCURRENCE_MUTABLE)})
                    IS DISTINCT FROM
                  (to_jsonb(OLD) - {_array(_OCCURRENCE_MUTABLE)})
            THEN
                RAISE EXCEPTION 'only a PENDING occurrence moves, and only its status marks'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_recurrence_occurrences_immutable';
            END IF;

            IF NEW.status = 'REALIZED' THEN
                SELECT m.*
                  INTO movement_row
                  FROM finance.movements m
                 WHERE m.id = NEW.movement_id;
                IF NOT FOUND
                   OR movement_row.role IS DISTINCT FROM 'STANDARD'
                   OR movement_row.installation_id IS DISTINCT FROM NEW.installation_id
                   OR movement_row.residence_id IS DISTINCT FROM NEW.residence_id
                   OR movement_row.account_id IS DISTINCT FROM NEW.account_id
                   OR movement_row.currency IS DISTINCT FROM NEW.currency
                   OR movement_row.result_effect IS DISTINCT FROM NEW.result_effect
                   OR movement_row.created_by_operator_id
                        IS DISTINCT FROM NEW.realized_by_operator_id
                   OR movement_row.created_at IS DISTINCT FROM transaction_timestamp()
                   OR NEW.realized_by_operator_id IS DISTINCT FROM NEW.owner_operator_id
               THEN
                    RAISE EXCEPTION 'realization must link the Movement written in this transaction'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_finance_recurrence_occurrences_movement_link';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_finance_enforce_recurrence_occurrence_transition "
        "BEFORE UPDATE ON finance.recurrence_occurrences "
        "FOR EACH ROW EXECUTE FUNCTION "
        "finance.enforce_recurrence_occurrence_transition()"
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

    def visible_account(table: str) -> str:
        # The account row policy decides who may see the account, so the rule and
        # its occurrences are exactly as visible as the account itself.
        return (
            "EXISTS (SELECT 1 FROM finance.accounts a "
            f"WHERE a.id = {table}.account_id "
            f"AND a.installation_id = {table}.installation_id "
            f"AND a.residence_id = {table}.residence_id "
            f"AND a.currency = {table}.currency)"
        )

    def owned_active_account(table: str) -> str:
        return (
            visible_account(table)[:-1]
            + f" AND a.owner_operator_id = {operator} AND a.status = 'ACTIVE')"
        )

    rules = "recurrences"
    rule_scope = (
        f"{rules}.installation_id = {installation} "
        f"AND {rules}.residence_id = {residence} "
        f"AND {active_membership(rules)}"
    )
    rule_owned = f"{rules}.owner_operator_id = {operator}"

    op.execute("ALTER TABLE finance.recurrences ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finance.recurrences FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY finance_recurrences_select ON finance.recurrences "
        f"FOR SELECT USING ({rule_scope} AND {visible_account(rules)})"
    )
    op.execute(
        "CREATE POLICY finance_recurrences_insert ON finance.recurrences "
        f"FOR INSERT WITH CHECK ({rule_scope} AND {rule_owned} "
        f"AND {rules}.version = 1 AND {rules}.status = 'ACTIVE' "
        f"AND {rules}.updated_by_operator_id = {operator} "
        f"AND {owned_active_account(rules)})"
    )
    # Read access never implies write access: only the owner moves a rule.
    op.execute(
        "CREATE POLICY finance_recurrences_update ON finance.recurrences "
        f"FOR UPDATE USING ({rule_scope} AND {rule_owned}) "
        f"WITH CHECK ({rule_scope} AND {rule_owned} "
        f"AND {rules}.updated_by_operator_id = {operator})"
    )

    occ = "recurrence_occurrences"
    occ_scope = (
        f"{occ}.installation_id = {installation} "
        f"AND {occ}.residence_id = {residence} "
        f"AND {active_membership(occ)}"
    )
    parent_visible = (
        "EXISTS (SELECT 1 FROM finance.recurrences r "
        f"WHERE r.id = {occ}.recurrence_id "
        f"AND r.installation_id = {occ}.installation_id "
        f"AND r.residence_id = {occ}.residence_id)"
    )
    parent_owned = parent_visible[:-1] + f" AND r.owner_operator_id = {operator})"

    op.execute("ALTER TABLE finance.recurrence_occurrences ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finance.recurrence_occurrences FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY finance_recurrence_occurrences_select "
        "ON finance.recurrence_occurrences "
        f"FOR SELECT USING ({occ_scope} AND {parent_visible} "
        f"AND {visible_account(occ)})"
    )
    op.execute(
        "CREATE POLICY finance_recurrence_occurrences_insert "
        "ON finance.recurrence_occurrences "
        f"FOR INSERT WITH CHECK ({occ_scope} AND {parent_owned} "
        f"AND {occ}.owner_operator_id = {operator} "
        f"AND {occ}.status = 'PENDING' "
        f"AND {owned_active_account(occ)})"
    )
    op.execute(
        "CREATE POLICY finance_recurrence_occurrences_update "
        "ON finance.recurrence_occurrences "
        f"FOR UPDATE USING ({occ_scope} AND {parent_owned}) "
        f"WITH CHECK ({occ_scope} AND {parent_owned} "
        f"AND {occ}.owner_operator_id = {operator})"
    )

    op.execute(f"GRANT SELECT, INSERT ON finance.recurrences TO {role}")
    op.execute(
        f"GRANT UPDATE ({', '.join(_RULE_MUTABLE)}) ON finance.recurrences TO {role}"
    )
    op.execute(f"GRANT SELECT, INSERT ON finance.recurrence_occurrences TO {role}")
    op.execute(
        f"GRANT UPDATE ({', '.join(_OCCURRENCE_MUTABLE)}) "
        f"ON finance.recurrence_occurrences TO {role}"
    )


def downgrade() -> None:
    role = _quoted_role()
    op.execute(
        f"REVOKE UPDATE ({', '.join(_OCCURRENCE_MUTABLE)}) "
        f"ON finance.recurrence_occurrences FROM {role}"
    )
    op.execute(f"REVOKE SELECT, INSERT ON finance.recurrence_occurrences FROM {role}")
    op.execute(
        f"REVOKE UPDATE ({', '.join(_RULE_MUTABLE)}) ON finance.recurrences FROM {role}"
    )
    op.execute(f"REVOKE SELECT, INSERT ON finance.recurrences FROM {role}")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_finance_enforce_recurrence_occurrence_transition "
        "ON finance.recurrence_occurrences"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS finance.enforce_recurrence_occurrence_transition()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_finance_validate_recurrence_occurrence_insert "
        "ON finance.recurrence_occurrences"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS finance.validate_recurrence_occurrence_insert()"
    )
    op.execute("DROP TABLE finance.recurrence_occurrences")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_finance_enforce_recurrence_row "
        "ON finance.recurrences"
    )
    op.execute("DROP FUNCTION IF EXISTS finance.enforce_recurrence_row()")
    op.execute("DROP TABLE finance.recurrences")
