# mypy: ignore-errors
"""Create transactional append-only financial audit trail.

Revision ID: 0018_financial_audit_trail
Revises: 0017_movement_allocations
Create Date: 2026-08-18
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0018_financial_audit_trail"
down_revision: str | None = "0017_movement_allocations"
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
        CREATE TABLE finance.audit_events (
            id uuid PRIMARY KEY,
            installation_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            actor_operator_id uuid NOT NULL,
            event_type varchar(32) NOT NULL,
            subject_type varchar(24) NOT NULL,
            subject_id uuid NOT NULL,
            related_subject_type varchar(24),
            related_subject_id uuid,
            event_schema_version smallint NOT NULL,
            occurred_at timestamptz NOT NULL,
            CONSTRAINT ck_finance_audit_events_id_uuid4 CHECK (
                id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            ),
            CONSTRAINT ck_finance_audit_events_event_type CHECK (
                event_type IN (
                    'ACCOUNT_CREATED',
                    'CATEGORY_CREATED',
                    'OPENING_BALANCE_CREATED',
                    'MOVEMENT_CREATED',
                    'MOVEMENT_REVERSED',
                    'TRANSFER_CREATED',
                    'TRANSFER_REVERSED',
                    'ALLOCATION_SET_CREATED',
                    'ALLOCATION_SET_REVISED'
                )
            ),
            CONSTRAINT ck_finance_audit_events_subject_type CHECK (
                subject_type IN (
                    'ACCOUNT', 'CATEGORY', 'OPENING_BALANCE',
                    'MOVEMENT', 'TRANSFER', 'ALLOCATION_SET'
                )
            ),
            CONSTRAINT ck_finance_audit_events_related_subject_type CHECK (
                related_subject_type IS NULL
                OR related_subject_type IN ('MOVEMENT', 'TRANSFER', 'ALLOCATION_SET')
            ),
            CONSTRAINT ck_finance_audit_events_schema_version CHECK (
                event_schema_version = 1
            ),
            CONSTRAINT ck_finance_audit_events_event_subject_shape CHECK (
                (event_type = 'ACCOUNT_CREATED'
                    AND subject_type = 'ACCOUNT'
                    AND related_subject_type IS NULL
                    AND related_subject_id IS NULL)
                OR (event_type = 'CATEGORY_CREATED'
                    AND subject_type = 'CATEGORY'
                    AND related_subject_type IS NULL
                    AND related_subject_id IS NULL)
                OR (event_type = 'OPENING_BALANCE_CREATED'
                    AND subject_type = 'OPENING_BALANCE'
                    AND related_subject_type IS NULL
                    AND related_subject_id IS NULL)
                OR (event_type = 'MOVEMENT_CREATED'
                    AND subject_type = 'MOVEMENT'
                    AND related_subject_type IS NULL
                    AND related_subject_id IS NULL)
                OR (event_type = 'MOVEMENT_REVERSED'
                    AND subject_type = 'MOVEMENT'
                    AND related_subject_type = 'MOVEMENT'
                    AND related_subject_id IS NOT NULL)
                OR (event_type = 'TRANSFER_CREATED'
                    AND subject_type = 'TRANSFER'
                    AND related_subject_type IS NULL
                    AND related_subject_id IS NULL)
                OR (event_type = 'TRANSFER_REVERSED'
                    AND subject_type = 'TRANSFER'
                    AND related_subject_type = 'TRANSFER'
                    AND related_subject_id IS NOT NULL)
                OR (event_type = 'ALLOCATION_SET_CREATED'
                    AND subject_type = 'ALLOCATION_SET'
                    AND related_subject_type IS NULL
                    AND related_subject_id IS NULL)
                OR (event_type = 'ALLOCATION_SET_REVISED'
                    AND subject_type = 'ALLOCATION_SET'
                    AND related_subject_type = 'ALLOCATION_SET'
                    AND related_subject_id IS NOT NULL)
            ),
            CONSTRAINT ck_finance_audit_events_distinct_related CHECK (
                related_subject_id IS NULL OR related_subject_id <> subject_id
            ),
            CONSTRAINT fk_finance_audit_events_actor_membership FOREIGN KEY (
                residence_id, actor_operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT uq_finance_audit_events_subject UNIQUE (
                subject_type, subject_id
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_finance_audit_events_actor_time "
        "ON finance.audit_events "
        "(residence_id, actor_operator_id, occurred_at, id)"
    )

    op.execute(
        """
        CREATE FUNCTION finance.append_financial_audit_event(
            p_installation_id uuid,
            p_residence_id uuid,
            p_actor_operator_id uuid,
            p_event_type varchar,
            p_subject_id uuid,
            p_related_subject_id uuid
        ) RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            current_installation_id uuid;
            current_residence_id uuid;
            current_operator_id uuid;
            derived_subject_type varchar(24);
            derived_related_subject_type varchar(24);
            new_event_id uuid;
            subject_valid boolean := false;
        BEGIN
            current_installation_id := NULLIF(
                pg_catalog.current_setting('app.current_installation_id', true), ''
            )::uuid;
            current_residence_id := NULLIF(
                pg_catalog.current_setting('app.current_residence_id', true), ''
            )::uuid;
            current_operator_id := NULLIF(
                pg_catalog.current_setting('app.current_operator_id', true), ''
            )::uuid;

            IF current_installation_id IS DISTINCT FROM p_installation_id
               OR current_residence_id IS DISTINCT FROM p_residence_id
               OR current_operator_id IS DISTINCT FROM p_actor_operator_id
            THEN
                RAISE EXCEPTION 'financial audit context mismatch'
                    USING ERRCODE = '42501';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                  FROM household.memberships hm
                 WHERE hm.installation_id = p_installation_id
                   AND hm.residence_id = p_residence_id
                   AND hm.operator_id = p_actor_operator_id
                   AND hm.status = 'active'
            ) THEN
                RAISE EXCEPTION 'financial audit actor is not active'
                    USING ERRCODE = '42501';
            END IF;

            CASE p_event_type
                WHEN 'ACCOUNT_CREATED' THEN
                    derived_subject_type := 'ACCOUNT';
                    derived_related_subject_type := NULL;
                    SELECT EXISTS (
                        SELECT 1
                          FROM finance.accounts a
                         WHERE a.id = p_subject_id
                           AND a.installation_id = p_installation_id
                           AND a.residence_id = p_residence_id
                           AND a.owner_operator_id = p_actor_operator_id
                           AND a.created_at = pg_catalog.transaction_timestamp()
                    ) INTO subject_valid;

                WHEN 'CATEGORY_CREATED' THEN
                    derived_subject_type := 'CATEGORY';
                    derived_related_subject_type := NULL;
                    SELECT EXISTS (
                        SELECT 1
                          FROM finance.categories c
                         WHERE c.id = p_subject_id
                           AND c.installation_id = p_installation_id
                           AND c.residence_id = p_residence_id
                           AND c.owner_operator_id = p_actor_operator_id
                           AND c.created_at = pg_catalog.transaction_timestamp()
                    ) INTO subject_valid;

                WHEN 'OPENING_BALANCE_CREATED' THEN
                    derived_subject_type := 'OPENING_BALANCE';
                    derived_related_subject_type := NULL;
                    SELECT EXISTS (
                        SELECT 1
                          FROM finance.account_opening_balances b
                         WHERE b.id = p_subject_id
                           AND b.installation_id = p_installation_id
                           AND b.residence_id = p_residence_id
                           AND b.created_by_operator_id = p_actor_operator_id
                           AND b.created_at = pg_catalog.transaction_timestamp()
                    ) INTO subject_valid;

                WHEN 'MOVEMENT_CREATED' THEN
                    derived_subject_type := 'MOVEMENT';
                    derived_related_subject_type := NULL;
                    SELECT EXISTS (
                        SELECT 1
                          FROM finance.movements m
                         WHERE m.id = p_subject_id
                           AND m.installation_id = p_installation_id
                           AND m.residence_id = p_residence_id
                           AND m.created_by_operator_id = p_actor_operator_id
                           AND m.role = 'STANDARD'
                           AND m.created_at = pg_catalog.transaction_timestamp()
                    ) INTO subject_valid;

                WHEN 'MOVEMENT_REVERSED' THEN
                    derived_subject_type := 'MOVEMENT';
                    derived_related_subject_type := 'MOVEMENT';
                    SELECT EXISTS (
                        SELECT 1
                          FROM finance.movements m
                          JOIN finance.movements original
                            ON original.id = m.reversal_of_id
                         WHERE m.id = p_subject_id
                           AND m.installation_id = p_installation_id
                           AND m.residence_id = p_residence_id
                           AND m.created_by_operator_id = p_actor_operator_id
                           AND m.role = 'REVERSAL'
                           AND m.reversal_of_id = p_related_subject_id
                           AND m.created_at = pg_catalog.transaction_timestamp()
                           AND original.installation_id = p_installation_id
                           AND original.residence_id = p_residence_id
                           AND original.role = 'STANDARD'
                    ) INTO subject_valid;

                WHEN 'TRANSFER_CREATED' THEN
                    derived_subject_type := 'TRANSFER';
                    derived_related_subject_type := NULL;
                    SELECT EXISTS (
                        SELECT 1
                          FROM finance.transfers t
                         WHERE t.id = p_subject_id
                           AND t.installation_id = p_installation_id
                           AND t.residence_id = p_residence_id
                           AND t.created_by_operator_id = p_actor_operator_id
                           AND t.role = 'STANDARD'
                           AND t.created_at = pg_catalog.transaction_timestamp()
                    ) INTO subject_valid;

                WHEN 'TRANSFER_REVERSED' THEN
                    derived_subject_type := 'TRANSFER';
                    derived_related_subject_type := 'TRANSFER';
                    SELECT EXISTS (
                        SELECT 1
                          FROM finance.transfers t
                          JOIN finance.transfers original
                            ON original.id = t.reversal_of_id
                         WHERE t.id = p_subject_id
                           AND t.installation_id = p_installation_id
                           AND t.residence_id = p_residence_id
                           AND t.created_by_operator_id = p_actor_operator_id
                           AND t.role = 'REVERSAL'
                           AND t.reversal_of_id = p_related_subject_id
                           AND t.created_at = pg_catalog.transaction_timestamp()
                           AND original.installation_id = p_installation_id
                           AND original.residence_id = p_residence_id
                           AND original.role = 'STANDARD'
                    ) INTO subject_valid;

                WHEN 'ALLOCATION_SET_CREATED' THEN
                    derived_subject_type := 'ALLOCATION_SET';
                    derived_related_subject_type := NULL;
                    SELECT EXISTS (
                        SELECT 1
                          FROM finance.movement_allocation_sets s
                         WHERE s.id = p_subject_id
                           AND s.installation_id = p_installation_id
                           AND s.residence_id = p_residence_id
                           AND s.created_by_operator_id = p_actor_operator_id
                           AND s.revision = 1
                           AND s.supersedes_id IS NULL
                           AND s.created_at = pg_catalog.transaction_timestamp()
                    ) INTO subject_valid;

                WHEN 'ALLOCATION_SET_REVISED' THEN
                    derived_subject_type := 'ALLOCATION_SET';
                    derived_related_subject_type := 'ALLOCATION_SET';
                    SELECT EXISTS (
                        SELECT 1
                          FROM finance.movement_allocation_sets s
                          JOIN finance.movement_allocation_sets predecessor
                            ON predecessor.id = s.supersedes_id
                         WHERE s.id = p_subject_id
                           AND s.installation_id = p_installation_id
                           AND s.residence_id = p_residence_id
                           AND s.created_by_operator_id = p_actor_operator_id
                           AND s.revision > 1
                           AND s.supersedes_id = p_related_subject_id
                           AND s.created_at = pg_catalog.transaction_timestamp()
                           AND predecessor.installation_id = p_installation_id
                           AND predecessor.residence_id = p_residence_id
                           AND predecessor.movement_id = s.movement_id
                    ) INTO subject_valid;

                ELSE
                    RAISE EXCEPTION 'unsupported financial audit event type'
                        USING ERRCODE = '22023';
            END CASE;

            IF derived_related_subject_type IS NULL THEN
                IF p_related_subject_id IS NOT NULL THEN
                    RAISE EXCEPTION 'financial audit related subject is forbidden'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF p_related_subject_id IS NULL
               OR p_related_subject_id = p_subject_id
            THEN
                RAISE EXCEPTION 'financial audit related subject is invalid'
                    USING ERRCODE = '23514';
            END IF;

            IF NOT subject_valid THEN
                RAISE EXCEPTION 'financial audit subject is not eligible'
                    USING ERRCODE = '23514';
            END IF;

            new_event_id := pg_catalog.gen_random_uuid();
            INSERT INTO finance.audit_events (
                id,
                installation_id,
                residence_id,
                actor_operator_id,
                event_type,
                subject_type,
                subject_id,
                related_subject_type,
                related_subject_id,
                event_schema_version,
                occurred_at
            ) VALUES (
                new_event_id,
                p_installation_id,
                p_residence_id,
                p_actor_operator_id,
                p_event_type,
                derived_subject_type,
                p_subject_id,
                derived_related_subject_type,
                p_related_subject_id,
                1,
                pg_catalog.transaction_timestamp()
            );

            RETURN new_event_id;
        END;
        $$
        """
    )

    installation = (
        "NULLIF(current_setting('app.current_installation_id', true), '')::uuid"
    )
    residence = "NULLIF(current_setting('app.current_residence_id', true), '')::uuid"
    operator = "NULLIF(current_setting('app.current_operator_id', true), '')::uuid"
    active_membership = (
        "EXISTS (SELECT 1 FROM household.memberships hm "
        "WHERE hm.installation_id = audit_events.installation_id "
        "AND hm.residence_id = audit_events.residence_id "
        f"AND hm.operator_id = {operator} AND hm.status = 'active')"
    )

    op.execute("ALTER TABLE finance.audit_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finance.audit_events FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY finance_audit_events_select ON finance.audit_events "
        "FOR SELECT USING ("
        f"installation_id = {installation} "
        f"AND residence_id = {residence} "
        f"AND actor_operator_id = {operator} "
        f"AND {active_membership})"
    )

    op.execute(f"REVOKE ALL ON finance.audit_events FROM {role}")
    op.execute(f"GRANT SELECT ON finance.audit_events TO {role}")
    op.execute(
        "REVOKE ALL ON FUNCTION finance.append_financial_audit_event("
        "uuid, uuid, uuid, varchar, uuid, uuid) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION finance.append_financial_audit_event("
        f"uuid, uuid, uuid, varchar, uuid, uuid) TO {role}"
    )


def downgrade() -> None:
    role = _quoted_role()
    op.execute(
        f"REVOKE EXECUTE ON FUNCTION finance.append_financial_audit_event("
        f"uuid, uuid, uuid, varchar, uuid, uuid) FROM {role}"
    )
    op.execute(f"REVOKE SELECT ON finance.audit_events FROM {role}")
    op.execute(
        "DROP FUNCTION finance.append_financial_audit_event("
        "uuid, uuid, uuid, varchar, uuid, uuid)"
    )
    op.execute("DROP TABLE finance.audit_events")
