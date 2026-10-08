# mypy: ignore-errors
"""Create financial goals and their append-only virtual allocation events.

``finance.goals`` is planning, never a ledger: no Movement, balance or allocated
amount is stored on it. ``finance.goal_allocation_events`` is the append-only history
of explicit virtual ``ALLOCATE`` (positive) / ``RELEASE`` (negative) events per goal
and account; what a goal holds is always the sum of its events. The runtime role may
only INSERT goals and, for the CAS edit, update the planning columns, and may only
INSERT events (UPDATE is rejected by a trigger, DELETE is not granted). ADR-0029.

Revision ID: 0028_financial_goals
Revises: 0027_recurrence_suggestions
Create Date: 2026-10-07
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0028_financial_goals"
down_revision: str | None = "0027_recurrence_suggestions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")

# The account lock is shared by the application and by the event trigger: both take
# the same transaction-scoped advisory lock so a path that forgot the lock cannot
# break the per-goal/account invariants.
_ACCOUNT_LOCK = (
    "pg_advisory_xact_lock(hashtextextended("
    "'meufinanceiro:goal-account:' || {account}::text, 0))"
)
_GOAL_LOCK = (
    "pg_advisory_xact_lock(hashtextextended('meufinanceiro:goal:' || {goal}::text, 0))"
)
_OWNER_LOCK = (
    "pg_advisory_xact_lock(hashtextextended("
    "'meufinanceiro:goal-owner:' || {owner}::text, 0))"
)


def _quoted_role() -> str:
    role_name = context.config.get_main_option("app_database_user")
    if not _ROLE_PATTERN.fullmatch(role_name):
        raise RuntimeError("invalid app_database_user for migration grants")
    return f'"{role_name}"'


def upgrade() -> None:
    role = _quoted_role()

    op.execute(
        r"""
        CREATE TABLE finance.goals (
            id uuid PRIMARY KEY,
            installation_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            owner_operator_id uuid NOT NULL,
            visibility_scope varchar(16) NOT NULL,
            title varchar(96) NOT NULL,
            description varchar(280),
            currency varchar(3) NOT NULL,
            target_amount numeric(24, 8) NOT NULL,
            target_date date,
            version integer NOT NULL,
            idempotency_key uuid NOT NULL,
            request_digest varchar(64) NOT NULL,
            updated_by_operator_id uuid NOT NULL,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            CONSTRAINT ck_finance_goals_id_uuid4 CHECK (
                id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ),
            CONSTRAINT ck_finance_goals_idempotency_uuid4 CHECK (
                idempotency_key::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ),
            CONSTRAINT ck_finance_goals_scope CHECK (
                visibility_scope IN ('PERSONAL', 'HOUSEHOLD')
            ),
            CONSTRAINT ck_finance_goals_title CHECK (
                length(btrim(title)) BETWEEN 1 AND 96
            ),
            CONSTRAINT ck_finance_goals_description CHECK (
                description IS NULL OR length(btrim(description)) BETWEEN 1 AND 280
            ),
            CONSTRAINT ck_finance_goals_currency CHECK (currency ~ '^[A-Z]{3}$'),
            CONSTRAINT ck_finance_goals_target_positive CHECK (
                target_amount > 0
                AND target_amount::text NOT IN ('NaN', 'Infinity', '-Infinity')
            ),
            CONSTRAINT ck_finance_goals_version CHECK (version >= 1),
            CONSTRAINT ck_finance_goals_request_digest CHECK (
                request_digest ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT ck_finance_goals_timestamps CHECK (updated_at >= created_at),
            CONSTRAINT fk_finance_goals_residence FOREIGN KEY (
                residence_id, installation_id
            ) REFERENCES household.residences (
                id, installation_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_goals_owner_membership FOREIGN KEY (
                residence_id, owner_operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_goals_updater_membership FOREIGN KEY (
                residence_id, updated_by_operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT uq_finance_goals_scope UNIQUE (
                id, installation_id, residence_id, currency
            ),
            CONSTRAINT uq_finance_goals_idempotency UNIQUE (
                installation_id, idempotency_key
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_finance_goals_owner ON finance.goals "
        "(residence_id, owner_operator_id, created_at, id)"
    )

    op.execute(
        r"""
        CREATE TABLE finance.goal_allocation_events (
            id uuid PRIMARY KEY,
            installation_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            goal_id uuid NOT NULL,
            account_id uuid NOT NULL,
            currency varchar(3) NOT NULL,
            kind varchar(16) NOT NULL,
            amount numeric(24, 8) NOT NULL,
            actor_operator_id uuid NOT NULL,
            idempotency_key uuid NOT NULL,
            request_digest varchar(64) NOT NULL,
            created_at timestamptz NOT NULL,
            CONSTRAINT ck_finance_goal_events_id_uuid4 CHECK (
                id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ),
            CONSTRAINT ck_finance_goal_events_idempotency_uuid4 CHECK (
                idempotency_key::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ),
            CONSTRAINT ck_finance_goal_events_kind CHECK (
                kind IN ('ALLOCATE', 'RELEASE')
            ),
            CONSTRAINT ck_finance_goal_events_currency CHECK (
                currency ~ '^[A-Z]{3}$'
            ),
            CONSTRAINT ck_finance_goal_events_amount_sign CHECK (
                amount::text NOT IN ('NaN', 'Infinity', '-Infinity')
                AND (
                    (kind = 'ALLOCATE' AND amount > 0)
                    OR (kind = 'RELEASE' AND amount < 0)
                )
            ),
            CONSTRAINT ck_finance_goal_events_request_digest CHECK (
                request_digest ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT fk_finance_goal_events_goal FOREIGN KEY (
                goal_id, installation_id, residence_id, currency
            ) REFERENCES finance.goals (
                id, installation_id, residence_id, currency
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_goal_events_account FOREIGN KEY (
                account_id, installation_id, residence_id, currency
            ) REFERENCES finance.accounts (
                id, installation_id, residence_id, currency
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_goal_events_actor_membership FOREIGN KEY (
                residence_id, actor_operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT uq_finance_goal_events_idempotency UNIQUE (
                installation_id, idempotency_key
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_finance_goal_events_goal "
        "ON finance.goal_allocation_events (goal_id, created_at, id)"
    )
    # Total allocated per account across every goal: an index-only sum.
    op.execute(
        "CREATE INDEX ix_finance_goal_events_account "
        "ON finance.goal_allocation_events (account_id) INCLUDE (amount)"
    )

    # Goal row shape: version 1 by its owner on insert (bounded per owner); only the
    # planning columns move and every update advances the version by exactly one.
    op.execute(
        f"""
        CREATE FUNCTION finance.enforce_goal_row()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            owned_goals integer;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.version IS DISTINCT FROM 1
                   OR NEW.updated_by_operator_id IS DISTINCT FROM NEW.owner_operator_id
                   OR NEW.updated_at IS DISTINCT FROM NEW.created_at
                THEN
                    RAISE EXCEPTION 'a goal starts at version 1 by its owner'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_finance_goals_initial_state';
                END IF;
                PERFORM {_OWNER_LOCK.format(owner="NEW.owner_operator_id")};
                SELECT count(*)
                  INTO owned_goals
                  FROM finance.goals g
                 WHERE g.installation_id = NEW.installation_id
                   AND g.residence_id = NEW.residence_id
                   AND g.owner_operator_id = NEW.owner_operator_id;
                IF owned_goals >= 200 THEN
                    RAISE EXCEPTION 'an owner may keep at most 200 goals per residence'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_finance_goals_owner_limit';
                END IF;
                RETURN NEW;
            END IF;

            IF NEW.version IS DISTINCT FROM OLD.version + 1
               OR NEW.updated_at < OLD.updated_at
               OR (to_jsonb(NEW) - 'title' - 'description' - 'target_amount'
                        - 'target_date' - 'version' - 'updated_at'
                        - 'updated_by_operator_id')
                    IS DISTINCT FROM
                  (to_jsonb(OLD) - 'title' - 'description' - 'target_amount'
                        - 'target_date' - 'version' - 'updated_at'
                        - 'updated_by_operator_id')
            THEN
                RAISE EXCEPTION 'goal identity is immutable and versions advance by one'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_goals_immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_finance_enforce_goal_row "
        "BEFORE INSERT OR UPDATE ON finance.goals "
        "FOR EACH ROW EXECUTE FUNCTION finance.enforce_goal_row()"
    )

    # Event integrity. The structure of a virtual allocation is decided by the
    # database, not by the caller: the owner of the goal is the actor, the account is
    # an eligible one (same owner, same audience, same currency via the FK, ACTIVE for
    # a new allocation), a goal/account never goes negative, and the history is
    # bounded. Availability against the canonical balance is the store's rule, taken
    # under the very same account lock (ADR-0029): it is not re-implemented in SQL.
    op.execute(
        f"""
        CREATE FUNCTION finance.validate_goal_allocation_event()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            goal_row finance.goals%ROWTYPE;
            account_row finance.accounts%ROWTYPE;
            virtual_net numeric(24, 8);
            event_count integer;
            account_count integer;
        BEGIN
            PERFORM {_ACCOUNT_LOCK.format(account="NEW.account_id")};
            PERFORM {_GOAL_LOCK.format(goal="NEW.goal_id")};

            IF NEW.created_at IS DISTINCT FROM transaction_timestamp() THEN
                RAISE EXCEPTION 'a goal event is recorded at the transaction instant'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_goal_events_instant';
            END IF;

            SELECT g.*
              INTO goal_row
              FROM finance.goals g
             WHERE g.id = NEW.goal_id;
            IF NOT FOUND
               OR goal_row.installation_id IS DISTINCT FROM NEW.installation_id
               OR goal_row.residence_id IS DISTINCT FROM NEW.residence_id
               OR goal_row.currency IS DISTINCT FROM NEW.currency
               OR goal_row.owner_operator_id IS DISTINCT FROM NEW.actor_operator_id
            THEN
                RAISE EXCEPTION 'a goal event must be written by the goal owner'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_goal_events_goal';
            END IF;

            SELECT a.*
              INTO account_row
              FROM finance.accounts a
             WHERE a.id = NEW.account_id;
            IF NOT FOUND
               OR account_row.installation_id IS DISTINCT FROM NEW.installation_id
               OR account_row.residence_id IS DISTINCT FROM NEW.residence_id
               OR account_row.currency IS DISTINCT FROM NEW.currency
               OR account_row.owner_operator_id
                    IS DISTINCT FROM goal_row.owner_operator_id
               OR account_row.visibility_scope
                    IS DISTINCT FROM goal_row.visibility_scope
               OR (NEW.kind = 'ALLOCATE' AND account_row.status IS DISTINCT FROM 'ACTIVE')
            THEN
                RAISE EXCEPTION 'goal account is not eligible'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_goal_events_account';
            END IF;

            SELECT COALESCE(sum(e.amount), 0)
              INTO virtual_net
              FROM finance.goal_allocation_events e
             WHERE e.goal_id = NEW.goal_id
               AND e.account_id = NEW.account_id;
            IF virtual_net + NEW.amount < 0 THEN
                RAISE EXCEPTION 'a goal cannot hold a negative virtual amount'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_goal_events_negative';
            END IF;

            SELECT count(*), count(DISTINCT e.account_id)
              INTO event_count, account_count
              FROM finance.goal_allocation_events e
             WHERE e.goal_id = NEW.goal_id;
            -- 25 events stay reserved for RELEASE (one per account), so a goal that
            -- reached its allocation budget can always give every account back.
            IF event_count >= 500
               OR (NEW.kind = 'ALLOCATE' AND event_count >= 475)
            THEN
                RAISE EXCEPTION 'a goal may keep at most 500 allocation events'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_goal_events_event_limit';
            END IF;
            IF account_count >= 25 AND NOT EXISTS (
                SELECT 1
                  FROM finance.goal_allocation_events e
                 WHERE e.goal_id = NEW.goal_id
                   AND e.account_id = NEW.account_id
            ) THEN
                RAISE EXCEPTION 'a goal may use at most 25 accounts'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_goal_events_account_limit';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_finance_validate_goal_allocation_event "
        "BEFORE INSERT ON finance.goal_allocation_events "
        "FOR EACH ROW EXECUTE FUNCTION finance.validate_goal_allocation_event()"
    )
    op.execute(
        """
        CREATE FUNCTION finance.reject_goal_allocation_event_update()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
            RAISE EXCEPTION 'goal allocation events are append-only'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'ck_finance_goal_events_immutable';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_finance_reject_goal_allocation_event_update "
        "BEFORE UPDATE ON finance.goal_allocation_events "
        "FOR EACH ROW EXECUTE FUNCTION finance.reject_goal_allocation_event_update()"
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

    goals = "goals"
    goal_scope = (
        f"{goals}.installation_id = {installation} "
        f"AND {goals}.residence_id = {residence} "
        f"AND {active_membership(goals)}"
    )
    goal_owned = f"{goals}.owner_operator_id = {operator}"

    op.execute("ALTER TABLE finance.goals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finance.goals FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY finance_goals_select ON finance.goals "
        f"FOR SELECT USING ({goal_scope} "
        f"AND ({goals}.visibility_scope = 'HOUSEHOLD' OR {goal_owned}))"
    )
    op.execute(
        "CREATE POLICY finance_goals_insert ON finance.goals "
        f"FOR INSERT WITH CHECK ({goal_scope} AND {goal_owned} "
        f"AND {goals}.visibility_scope IN ('PERSONAL', 'HOUSEHOLD') "
        f"AND {goals}.version = 1 "
        f"AND {goals}.updated_by_operator_id = {operator})"
    )
    # Read access to a HOUSEHOLD goal never implies write access: only the owner.
    op.execute(
        "CREATE POLICY finance_goals_update ON finance.goals "
        f"FOR UPDATE USING ({goal_scope} AND {goal_owned}) "
        f"WITH CHECK ({goal_scope} AND {goal_owned} "
        f"AND {goals}.updated_by_operator_id = {operator})"
    )

    events = "goal_allocation_events"
    event_scope = (
        f"{events}.installation_id = {installation} "
        f"AND {events}.residence_id = {residence} "
        f"AND {active_membership(events)}"
    )
    # The goal row policy decides who may see a goal, so an event is exactly as
    # visible as the goal it belongs to.
    parent_visible = (
        "EXISTS (SELECT 1 FROM finance.goals g "
        f"WHERE g.id = {events}.goal_id "
        f"AND g.installation_id = {events}.installation_id "
        f"AND g.residence_id = {events}.residence_id "
        f"AND g.currency = {events}.currency)"
    )
    parent_owned = parent_visible[:-1] + f" AND g.owner_operator_id = {operator})"
    visible_account = (
        "EXISTS (SELECT 1 FROM finance.accounts a "
        f"WHERE a.id = {events}.account_id "
        f"AND a.installation_id = {events}.installation_id "
        f"AND a.residence_id = {events}.residence_id "
        f"AND a.currency = {events}.currency)"
    )
    op.execute("ALTER TABLE finance.goal_allocation_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finance.goal_allocation_events FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY finance_goal_events_select ON finance.goal_allocation_events "
        f"FOR SELECT USING ({event_scope} AND {parent_visible})"
    )
    op.execute(
        "CREATE POLICY finance_goal_events_insert ON finance.goal_allocation_events "
        f"FOR INSERT WITH CHECK ({event_scope} "
        f"AND {events}.actor_operator_id = {operator} "
        f"AND {parent_owned} AND {visible_account})"
    )

    op.execute(f"GRANT SELECT, INSERT ON finance.goals TO {role}")
    op.execute(
        "GRANT UPDATE (title, description, target_amount, target_date, version, "
        f"updated_at, updated_by_operator_id) ON finance.goals TO {role}"
    )
    op.execute(f"GRANT SELECT, INSERT ON finance.goal_allocation_events TO {role}")


def downgrade() -> None:
    role = _quoted_role()
    op.execute(f"REVOKE SELECT, INSERT ON finance.goal_allocation_events FROM {role}")
    op.execute(
        "REVOKE UPDATE (title, description, target_amount, target_date, version, "
        f"updated_at, updated_by_operator_id) ON finance.goals FROM {role}"
    )
    op.execute(f"REVOKE SELECT, INSERT ON finance.goals FROM {role}")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_finance_reject_goal_allocation_event_update "
        "ON finance.goal_allocation_events"
    )
    op.execute("DROP FUNCTION IF EXISTS finance.reject_goal_allocation_event_update()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_finance_validate_goal_allocation_event "
        "ON finance.goal_allocation_events"
    )
    op.execute("DROP FUNCTION IF EXISTS finance.validate_goal_allocation_event()")
    op.execute("DROP TABLE finance.goal_allocation_events")
    op.execute("DROP TRIGGER IF EXISTS trg_finance_enforce_goal_row ON finance.goals")
    op.execute("DROP FUNCTION IF EXISTS finance.enforce_goal_row()")
    op.execute("DROP TABLE finance.goals")
