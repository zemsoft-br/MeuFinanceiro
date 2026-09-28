"""SQLAlchemy metadata for append-only canonical financial Movements."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from meufinanceiro_persistence.schema import metadata

financial_movements = Table(
    "movements",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("account_id", UUID(as_uuid=True), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("amount", Numeric(24, 8), nullable=False),
    Column("result_effect", String(16), nullable=False),
    Column("role", String(16), nullable=False),
    Column("effective_date", Date(), nullable=False),
    Column("competence_date", Date(), nullable=False),
    Column("description", String(256), nullable=True),
    Column("reversal_of_id", UUID(as_uuid=True), nullable=True),
    Column("reversal_target_role", String(16), nullable=True),
    Column("reversal_reason", String(256), nullable=True),
    Column("created_by_operator_id", UUID(as_uuid=True), nullable=False),
    Column("idempotency_key", UUID(as_uuid=True), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "id::text ~ "
        "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
        name="ck_finance_movements_id_uuid4",
    ),
    CheckConstraint(
        "idempotency_key::text ~ "
        "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
        name="ck_finance_movements_idempotency_uuid4",
    ),
    CheckConstraint(
        "currency ~ '^[A-Z]{3}$'",
        name="ck_finance_movements_currency",
    ),
    CheckConstraint(
        "amount <> 0 AND amount::text NOT IN ('NaN', 'Infinity', '-Infinity')",
        name="ck_finance_movements_amount",
    ),
    CheckConstraint(
        "result_effect IN ('INCOME', 'EXPENSE', 'NEUTRAL')",
        name="ck_finance_movements_result_effect",
    ),
    CheckConstraint(
        "role IN ('STANDARD', 'REVERSAL')",
        name="ck_finance_movements_role",
    ),
    CheckConstraint(
        "request_digest ~ '^[0-9a-f]{64}$'",
        name="ck_finance_movements_request_digest",
    ),
    CheckConstraint(
        "role = 'REVERSAL' OR result_effect = 'NEUTRAL' "
        "OR (result_effect = 'INCOME' AND amount > 0) "
        "OR (result_effect = 'EXPENSE' AND amount < 0)",
        name="ck_finance_movements_standard_sign",
    ),
    CheckConstraint(
        "(role = 'STANDARD' AND description IS NOT NULL "
        "AND length(btrim(description)) BETWEEN 1 AND 256 "
        "AND reversal_of_id IS NULL AND reversal_target_role IS NULL "
        "AND reversal_reason IS NULL) OR "
        "(role = 'REVERSAL' AND description IS NULL "
        "AND reversal_of_id IS NOT NULL AND reversal_target_role = 'STANDARD' "
        "AND reversal_reason IS NOT NULL "
        "AND length(btrim(reversal_reason)) BETWEEN 1 AND 256)",
        name="ck_finance_movements_role_shape",
    ),
    ForeignKeyConstraint(
        ["account_id", "installation_id", "residence_id", "currency"],
        [
            "finance.accounts.id",
            "finance.accounts.installation_id",
            "finance.accounts.residence_id",
            "finance.accounts.currency",
        ],
        ondelete="RESTRICT",
        name="fk_finance_movements_account_scope",
    ),
    ForeignKeyConstraint(
        ["residence_id", "created_by_operator_id"],
        ["household.memberships.residence_id", "household.memberships.operator_id"],
        ondelete="RESTRICT",
        name="fk_finance_movements_creator_membership",
    ),
    UniqueConstraint(
        "id",
        "installation_id",
        "residence_id",
        "account_id",
        "currency",
        "result_effect",
        "role",
        name="uq_finance_movements_reversal_target",
    ),
    ForeignKeyConstraint(
        [
            "reversal_of_id",
            "installation_id",
            "residence_id",
            "account_id",
            "currency",
            "result_effect",
            "reversal_target_role",
        ],
        [
            "finance.movements.id",
            "finance.movements.installation_id",
            "finance.movements.residence_id",
            "finance.movements.account_id",
            "finance.movements.currency",
            "finance.movements.result_effect",
            "finance.movements.role",
        ],
        ondelete="RESTRICT",
        name="fk_finance_movements_reversal_target",
    ),
    UniqueConstraint(
        "installation_id",
        "idempotency_key",
        name="uq_finance_movements_idempotency",
    ),
    UniqueConstraint(
        "reversal_of_id",
        name="uq_finance_movements_one_reversal",
    ),
    schema="finance",
)

Index(
    "ix_finance_movements_account_effective",
    financial_movements.c.residence_id,
    financial_movements.c.account_id,
    financial_movements.c.effective_date,
    financial_movements.c.created_at,
    financial_movements.c.id,
)
Index(
    "ix_finance_movements_account_competence",
    financial_movements.c.residence_id,
    financial_movements.c.account_id,
    financial_movements.c.competence_date,
    financial_movements.c.created_at,
    financial_movements.c.id,
)

__all__ = ["financial_movements"]
