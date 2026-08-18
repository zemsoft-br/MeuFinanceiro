# mypy: ignore-errors
"""Require audit coverage for successful financial mutations.

Revision ID: 0019_financial_audit_enforcement
Revises: 0018_financial_audit_trail
Create Date: 2026-08-18
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0019_financial_audit_enforcement"
down_revision: str | None = "0018_financial_audit_trail"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SECURITY DEFINER is the only normal writer. Keeping RLS enabled while
    # allowing the table owner to bypass it avoids coupling the function to a
    # migration role with BYPASSRLS. The runtime still has SELECT only.
    op.execute("ALTER TABLE finance.audit_events NO FORCE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE FUNCTION finance.require_financial_audit_event()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            expected_event_type varchar(32);
            expected_subject_type varchar(24);
            transfer_id uuid;
            transfer_role varchar(16);
        BEGIN
            IF TG_TABLE_SCHEMA <> 'finance' THEN
                RAISE EXCEPTION 'financial audit enforcement schema mismatch'
                    USING ERRCODE = '23514';
            END IF;

            CASE TG_TABLE_NAME
                WHEN 'accounts' THEN
                    expected_event_type := 'ACCOUNT_CREATED';
                    expected_subject_type := 'ACCOUNT';

                WHEN 'categories' THEN
                    expected_event_type := 'CATEGORY_CREATED';
                    expected_subject_type := 'CATEGORY';

                WHEN 'account_opening_balances' THEN
                    expected_event_type := 'OPENING_BALANCE_CREATED';
                    expected_subject_type := 'OPENING_BALANCE';

                WHEN 'movements' THEN
                    SELECT l.transfer_id, t.role
                      INTO transfer_id, transfer_role
                      FROM finance.transfer_legs l
                      JOIN finance.transfers t ON t.id = l.transfer_id
                     WHERE l.movement_id = NEW.id;

                    IF transfer_id IS NOT NULL THEN
                        expected_subject_type := 'TRANSFER';
                        expected_event_type := CASE transfer_role
                            WHEN 'STANDARD' THEN 'TRANSFER_CREATED'
                            WHEN 'REVERSAL' THEN 'TRANSFER_REVERSED'
                            ELSE NULL
                        END;
                        IF expected_event_type IS NULL OR NOT EXISTS (
                            SELECT 1
                              FROM finance.audit_events ae
                             WHERE ae.subject_type = expected_subject_type
                               AND ae.subject_id = transfer_id
                               AND ae.event_type = expected_event_type
                               AND ae.installation_id = NEW.installation_id
                               AND ae.residence_id = NEW.residence_id
                        ) THEN
                            RAISE EXCEPTION 'transfer Movement has no transactional audit event'
                                USING ERRCODE = '23514',
                                      CONSTRAINT = 'ck_finance_movement_audit_required';
                        END IF;
                        RETURN NEW;
                    END IF;

                    expected_subject_type := 'MOVEMENT';
                    expected_event_type := CASE NEW.role
                        WHEN 'STANDARD' THEN 'MOVEMENT_CREATED'
                        WHEN 'REVERSAL' THEN 'MOVEMENT_REVERSED'
                        ELSE NULL
                    END;

                WHEN 'transfers' THEN
                    expected_subject_type := 'TRANSFER';
                    expected_event_type := CASE NEW.role
                        WHEN 'STANDARD' THEN 'TRANSFER_CREATED'
                        WHEN 'REVERSAL' THEN 'TRANSFER_REVERSED'
                        ELSE NULL
                    END;

                WHEN 'movement_allocation_sets' THEN
                    expected_subject_type := 'ALLOCATION_SET';
                    expected_event_type := CASE
                        WHEN NEW.revision = 1 AND NEW.supersedes_id IS NULL
                            THEN 'ALLOCATION_SET_CREATED'
                        WHEN NEW.revision > 1 AND NEW.supersedes_id IS NOT NULL
                            THEN 'ALLOCATION_SET_REVISED'
                        ELSE NULL
                    END;

                ELSE
                    RAISE EXCEPTION 'unsupported financial audit enforcement target'
                        USING ERRCODE = '23514';
            END CASE;

            IF expected_event_type IS NULL OR NOT EXISTS (
                SELECT 1
                  FROM finance.audit_events ae
                 WHERE ae.subject_type = expected_subject_type
                   AND ae.subject_id = NEW.id
                   AND ae.event_type = expected_event_type
                   AND ae.installation_id = NEW.installation_id
                   AND ae.residence_id = NEW.residence_id
            ) THEN
                RAISE EXCEPTION 'financial mutation has no transactional audit event'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_finance_audit_required';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )

    for table_name in (
        "accounts",
        "categories",
        "account_opening_balances",
        "movements",
        "transfers",
        "movement_allocation_sets",
    ):
        op.execute(
            "CREATE CONSTRAINT TRIGGER "
            f"trg_finance_{table_name}_audit_required "
            f"AFTER INSERT ON finance.{table_name} "
            "DEFERRABLE INITIALLY DEFERRED "
            "FOR EACH ROW EXECUTE FUNCTION finance.require_financial_audit_event()"
        )


def downgrade() -> None:
    for table_name in reversed(
        (
            "accounts",
            "categories",
            "account_opening_balances",
            "movements",
            "transfers",
            "movement_allocation_sets",
        )
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_finance_{table_name}_audit_required "
            f"ON finance.{table_name}"
        )
    op.execute("DROP FUNCTION IF EXISTS finance.require_financial_audit_event()")
    op.execute("ALTER TABLE finance.audit_events FORCE ROW LEVEL SECURITY")
