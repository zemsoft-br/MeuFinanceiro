# mypy: ignore-errors
"""Append-only decisions about derived recurrence suggestions (ADR-0028).

A suggestion is never stored: it is derived at read time. What persists is the
user's explicit decision about one suggestion fingerprint:

* ``DISMISSED`` hides the suggestion for the operator who dismissed it, only;
* ``ACCEPTED`` is the provenance of the recurrence the owner created from it and is
  readable by the whole audience of the account, so the suggestion stops appearing.

The runtime role may INSERT and SELECT; nothing can UPDATE a decision (a trigger
refuses it even for privileged roles) and there is no DELETE grant. An ``ACCEPTED``
row may only point at a recurrence created in the very same transaction, by the same
owner, for the same account: acceptance and the rule it creates are atomic.

A partial index serves the detector scan (realized STANDARD EXPENSE Movements by
residence and date) without touching ``finance.movements`` itself.

Revision ID: 0027_recurrence_suggestions
Revises: 0026_recurrence_revisions
Create Date: 2026-10-07
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0027_recurrence_suggestions"
down_revision: str | None = "0026_recurrence_revisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")
_UUID4 = "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'"


def _quoted_role() -> str:
    role_name = context.config.get_main_option("app_database_user")
    if not _ROLE_PATTERN.fullmatch(role_name):
        raise RuntimeError("invalid app_database_user for migration grants")
    return f'"{role_name}"'


def upgrade() -> None:
    role = _quoted_role()

    op.execute(
        f"""
        CREATE TABLE finance.recurrence_suggestion_decisions (
            id uuid PRIMARY KEY,
            installation_id uuid NOT NULL,
            residence_id uuid NOT NULL,
            account_id uuid NOT NULL,
            operator_id uuid NOT NULL,
            currency varchar(3) NOT NULL,
            fingerprint varchar(64) NOT NULL,
            decision varchar(16) NOT NULL,
            recurrence_id uuid,
            evidence_digest varchar(64) NOT NULL,
            decided_at timestamptz NOT NULL,
            CONSTRAINT ck_finance_recurrence_decisions_id_uuid4 CHECK (
                id::text ~ {_UUID4}
            ),
            CONSTRAINT ck_finance_recurrence_decisions_currency CHECK (
                currency ~ '^[A-Z]{{3}}$'
            ),
            CONSTRAINT ck_finance_recurrence_decisions_fingerprint CHECK (
                fingerprint ~ '^[0-9a-f]{{64}}$'
            ),
            CONSTRAINT ck_finance_recurrence_decisions_digest CHECK (
                evidence_digest ~ '^[0-9a-f]{{64}}$'
            ),
            CONSTRAINT ck_finance_recurrence_decisions_decision CHECK (
                decision IN ('ACCEPTED', 'DISMISSED')
            ),
            CONSTRAINT ck_finance_recurrence_decisions_shape CHECK (
                (decision = 'ACCEPTED') = (recurrence_id IS NOT NULL)
            ),
            CONSTRAINT fk_finance_recurrence_decisions_residence FOREIGN KEY (
                residence_id, installation_id
            ) REFERENCES household.residences (
                id, installation_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_recurrence_decisions_account FOREIGN KEY (
                account_id, installation_id, residence_id, currency
            ) REFERENCES finance.accounts (
                id, installation_id, residence_id, currency
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_recurrence_decisions_operator_membership FOREIGN KEY (
                residence_id, operator_id
            ) REFERENCES household.memberships (
                residence_id, operator_id
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_finance_recurrence_decisions_recurrence FOREIGN KEY (
                recurrence_id, installation_id, residence_id
            ) REFERENCES finance.recurrences (
                id, installation_id, residence_id
            ) ON DELETE RESTRICT,
            CONSTRAINT uq_finance_recurrence_decisions_operator_fingerprint UNIQUE (
                installation_id, operator_id, fingerprint
            ),
            CONSTRAINT uq_finance_recurrence_decisions_recurrence UNIQUE (
                recurrence_id
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_finance_recurrence_decisions_account "
        "ON finance.recurrence_suggestion_decisions (residence_id, account_id)"
    )
    # Detector scan: realized STANDARD EXPENSE Movements by residence and date.
    op.execute(
        "CREATE INDEX ix_finance_movements_expense_scan "
        "ON finance.movements (residence_id, effective_date) "
        "WHERE role = 'STANDARD' AND result_effect = 'EXPENSE'"
    )

    # A decision is shaped by the database, not by the caller: the instant is the
    # transaction's, and an ACCEPTED decision links a rule created right now by the
    # same owner for the same account.
    op.execute(
        """
        CREATE FUNCTION finance.validate_recurrence_suggestion_decision()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            rule_row finance.recurrences%ROWTYPE;
        BEGIN
            IF NEW.decided_at IS DISTINCT FROM transaction_timestamp() THEN
                RAISE EXCEPTION 'a decision is recorded at the transaction instant'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_recurrence_decisions_instant';
            END IF;

            IF NEW.decision = 'ACCEPTED' THEN
                SELECT r.*
                  INTO rule_row
                  FROM finance.recurrences r
                 WHERE r.id = NEW.recurrence_id;
                IF NOT FOUND
                   OR rule_row.installation_id IS DISTINCT FROM NEW.installation_id
                   OR rule_row.residence_id IS DISTINCT FROM NEW.residence_id
                   OR rule_row.account_id IS DISTINCT FROM NEW.account_id
                   OR rule_row.currency IS DISTINCT FROM NEW.currency
                   OR rule_row.result_effect IS DISTINCT FROM 'EXPENSE'
                   OR rule_row.owner_operator_id IS DISTINCT FROM NEW.operator_id
                   OR rule_row.created_at IS DISTINCT FROM transaction_timestamp()
                THEN
                    RAISE EXCEPTION 'an accepted suggestion must link the recurrence created in this transaction'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_finance_recurrence_decisions_link';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_finance_validate_recurrence_suggestion_decision "
        "BEFORE INSERT ON finance.recurrence_suggestion_decisions "
        "FOR EACH ROW EXECUTE FUNCTION "
        "finance.validate_recurrence_suggestion_decision()"
    )
    op.execute(
        """
        CREATE FUNCTION finance.reject_recurrence_suggestion_decision_update()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
            RAISE EXCEPTION 'recurrence suggestion decisions are append-only'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'ck_finance_recurrence_decisions_immutable';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_finance_reject_recurrence_suggestion_decision_update "
        "BEFORE UPDATE ON finance.recurrence_suggestion_decisions "
        "FOR EACH ROW EXECUTE FUNCTION "
        "finance.reject_recurrence_suggestion_decision_update()"
    )

    installation = (
        "NULLIF(current_setting('app.current_installation_id', true), '')::uuid"
    )
    residence = "NULLIF(current_setting('app.current_residence_id', true), '')::uuid"
    operator = "NULLIF(current_setting('app.current_operator_id', true), '')::uuid"
    d = "recurrence_suggestion_decisions"
    scope = (
        f"{d}.installation_id = {installation} "
        f"AND {d}.residence_id = {residence} "
        "AND EXISTS (SELECT 1 FROM household.memberships hm "
        f"WHERE hm.installation_id = {d}.installation_id "
        f"AND hm.residence_id = {d}.residence_id "
        f"AND hm.operator_id = {operator} AND hm.status = 'active')"
    )
    # The account row policy decides who may see the account, so a decision is
    # exactly as visible as the account it is about (PERSONAL / SHARED / HOUSEHOLD).
    visible_account = (
        "EXISTS (SELECT 1 FROM finance.accounts a "
        f"WHERE a.id = {d}.account_id "
        f"AND a.installation_id = {d}.installation_id "
        f"AND a.residence_id = {d}.residence_id "
        f"AND a.currency = {d}.currency)"
    )
    owned_active_account = (
        visible_account[:-1] + f" AND a.owner_operator_id = {operator} "
        "AND a.status = 'ACTIVE')"
    )
    owned_rule = (
        "EXISTS (SELECT 1 FROM finance.recurrences r "
        f"WHERE r.id = {d}.recurrence_id "
        f"AND r.installation_id = {d}.installation_id "
        f"AND r.residence_id = {d}.residence_id "
        f"AND r.owner_operator_id = {operator})"
    )

    op.execute(
        "ALTER TABLE finance.recurrence_suggestion_decisions ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE finance.recurrence_suggestion_decisions FORCE ROW LEVEL SECURITY"
    )
    # DISMISSED is personal; ACCEPTED is provenance of a shared rule and follows the
    # account audience.
    op.execute(
        "CREATE POLICY finance_recurrence_decisions_select "
        "ON finance.recurrence_suggestion_decisions "
        f"FOR SELECT USING ({scope} AND {visible_account} "
        f"AND ({d}.decision = 'ACCEPTED' OR {d}.operator_id = {operator}))"
    )
    op.execute(
        "CREATE POLICY finance_recurrence_decisions_insert "
        "ON finance.recurrence_suggestion_decisions "
        f"FOR INSERT WITH CHECK ({scope} AND {d}.operator_id = {operator} "
        f"AND {visible_account} "
        f"AND ({d}.decision = 'DISMISSED' "
        f"OR ({owned_active_account} AND {owned_rule})))"
    )

    op.execute(
        f"GRANT SELECT, INSERT ON finance.recurrence_suggestion_decisions TO {role}"
    )


def downgrade() -> None:
    role = _quoted_role()
    op.execute(
        f"REVOKE SELECT, INSERT ON finance.recurrence_suggestion_decisions FROM {role}"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS "
        "trg_finance_reject_recurrence_suggestion_decision_update "
        "ON finance.recurrence_suggestion_decisions"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS finance.reject_recurrence_suggestion_decision_update()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_finance_validate_recurrence_suggestion_decision "
        "ON finance.recurrence_suggestion_decisions"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS finance.validate_recurrence_suggestion_decision()"
    )
    op.execute("DROP INDEX finance.ix_finance_movements_expense_scan")
    op.execute("DROP TABLE finance.recurrence_suggestion_decisions")
