"""SQLAlchemy metadata for manual monthly recurrences (planning, never a ledger).

``finance.recurrences`` is the rule (the model) with the CAS ``version``.
``finance.recurrence_occurrences`` is one persisted instance per rule and month with
the snapshot of the revision that made it. The only link to the ledger is the
occurrence's ``movement_id``, written once, in the transaction that creates the
Movement. ``finance.movements`` knows nothing about recurrences.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from meufinanceiro_persistence.schema import metadata

_UUID4 = "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'"

financial_recurrences = Table(
    "recurrences",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("account_id", UUID(as_uuid=True), nullable=False),
    Column("owner_operator_id", UUID(as_uuid=True), nullable=False),
    Column("description", String(256), nullable=False),
    Column("result_effect", String(16), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("expected_amount", Numeric(24, 8), nullable=False),
    Column("frequency", String(16), nullable=False),
    Column("start_date", Date(), nullable=False),
    Column("day_of_month", Integer(), nullable=False),
    Column("end_date", Date(), nullable=True),
    Column("status", String(16), nullable=False),
    Column("version", Integer(), nullable=False),
    Column("idempotency_key", UUID(as_uuid=True), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("updated_by_operator_id", UUID(as_uuid=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(f"id::text ~ {_UUID4}", name="ck_finance_recurrences_id_uuid4"),
    CheckConstraint(
        f"idempotency_key::text ~ {_UUID4}",
        name="ck_finance_recurrences_idempotency_uuid4",
    ),
    CheckConstraint(
        "length(btrim(description)) BETWEEN 1 AND 256",
        name="ck_finance_recurrences_description",
    ),
    CheckConstraint(
        "result_effect IN ('INCOME', 'EXPENSE')",
        name="ck_finance_recurrences_effect",
    ),
    CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_finance_recurrences_currency"),
    CheckConstraint(
        "expected_amount > 0 AND expected_amount::text NOT IN "
        "('NaN', 'Infinity', '-Infinity')",
        name="ck_finance_recurrences_expected_positive",
    ),
    CheckConstraint("frequency = 'MONTHLY'", name="ck_finance_recurrences_frequency"),
    CheckConstraint("day_of_month BETWEEN 1 AND 31", name="ck_finance_recurrences_day"),
    CheckConstraint(
        "end_date IS NULL OR end_date >= start_date",
        name="ck_finance_recurrences_dates",
    ),
    CheckConstraint(
        "status IN ('ACTIVE', 'PAUSED')", name="ck_finance_recurrences_status"
    ),
    CheckConstraint("version >= 1", name="ck_finance_recurrences_version"),
    CheckConstraint(
        "request_digest ~ '^[0-9a-f]{64}$'",
        name="ck_finance_recurrences_request_digest",
    ),
    CheckConstraint(
        "updated_at >= created_at", name="ck_finance_recurrences_timestamps"
    ),
    ForeignKeyConstraint(
        ["residence_id", "installation_id"],
        ["household.residences.id", "household.residences.installation_id"],
        ondelete="RESTRICT",
        name="fk_finance_recurrences_residence",
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
        name="fk_finance_recurrences_account",
    ),
    ForeignKeyConstraint(
        ["residence_id", "owner_operator_id"],
        ["household.memberships.residence_id", "household.memberships.operator_id"],
        ondelete="RESTRICT",
        name="fk_finance_recurrences_owner_membership",
    ),
    ForeignKeyConstraint(
        ["residence_id", "updated_by_operator_id"],
        ["household.memberships.residence_id", "household.memberships.operator_id"],
        ondelete="RESTRICT",
        name="fk_finance_recurrences_updater_membership",
    ),
    UniqueConstraint(
        "id", "installation_id", "residence_id", name="uq_finance_recurrences_scope"
    ),
    UniqueConstraint(
        "installation_id",
        "idempotency_key",
        name="uq_finance_recurrences_idempotency",
    ),
    schema="finance",
)

Index(
    "ix_finance_recurrences_residence",
    financial_recurrences.c.residence_id,
    financial_recurrences.c.created_at,
    financial_recurrences.c.id,
)
Index(
    "ix_finance_recurrences_account",
    financial_recurrences.c.residence_id,
    financial_recurrences.c.account_id,
)

financial_recurrence_occurrences = Table(
    "recurrence_occurrences",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("recurrence_id", UUID(as_uuid=True), nullable=False),
    Column("account_id", UUID(as_uuid=True), nullable=False),
    Column("owner_operator_id", UUID(as_uuid=True), nullable=False),
    Column("period_start", Date(), nullable=False),
    Column("scheduled_date", Date(), nullable=False),
    Column("rule_version", Integer(), nullable=False),
    Column("result_effect", String(16), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("expected_amount", Numeric(24, 8), nullable=False),
    Column("description", String(256), nullable=False),
    Column("status", String(16), nullable=False),
    Column("movement_id", UUID(as_uuid=True), nullable=True),
    Column("realization_idempotency_key", UUID(as_uuid=True), nullable=True),
    Column("realization_request_digest", String(64), nullable=True),
    Column("realized_at", DateTime(timezone=True), nullable=True),
    Column("realized_by_operator_id", UUID(as_uuid=True), nullable=True),
    Column("skipped_at", DateTime(timezone=True), nullable=True),
    Column("superseded_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        f"id::text ~ {_UUID4}", name="ck_finance_recurrence_occurrences_id_uuid4"
    ),
    CheckConstraint(
        "status IN ('PENDING', 'REALIZED', 'SKIPPED', 'SUPERSEDED')",
        name="ck_finance_recurrence_occurrences_status",
    ),
    CheckConstraint(
        "result_effect IN ('INCOME', 'EXPENSE')",
        name="ck_finance_recurrence_occurrences_effect",
    ),
    CheckConstraint(
        "expected_amount > 0 AND expected_amount::text NOT IN "
        "('NaN', 'Infinity', '-Infinity')",
        name="ck_finance_recurrence_occurrences_expected_positive",
    ),
    ForeignKeyConstraint(
        ["recurrence_id", "installation_id", "residence_id"],
        [
            "finance.recurrences.id",
            "finance.recurrences.installation_id",
            "finance.recurrences.residence_id",
        ],
        ondelete="RESTRICT",
        name="fk_finance_recurrence_occurrences_rule",
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
        name="fk_finance_recurrence_occurrences_account",
    ),
    ForeignKeyConstraint(
        ["movement_id"],
        ["finance.movements.id"],
        ondelete="RESTRICT",
        name="fk_finance_recurrence_occurrences_movement",
    ),
    UniqueConstraint(
        "installation_id",
        "realization_idempotency_key",
        name="uq_finance_recurrence_occurrences_realization_key",
    ),
    UniqueConstraint("movement_id", name="uq_finance_recurrence_occurrences_movement"),
    schema="finance",
)

Index(
    "uq_finance_recurrence_occurrences_month",
    financial_recurrence_occurrences.c.recurrence_id,
    financial_recurrence_occurrences.c.period_start,
    unique=True,
    postgresql_where=text("status <> 'SUPERSEDED'"),
)
Index(
    "ix_finance_recurrence_occurrences_period",
    financial_recurrence_occurrences.c.residence_id,
    financial_recurrence_occurrences.c.period_start,
    financial_recurrence_occurrences.c.recurrence_id,
)
Index(
    "ix_finance_recurrence_occurrences_rule",
    financial_recurrence_occurrences.c.recurrence_id,
    financial_recurrence_occurrences.c.period_start,
    financial_recurrence_occurrences.c.created_at,
)
Index(
    "ix_finance_recurrence_occurrences_pending",
    financial_recurrence_occurrences.c.recurrence_id,
    financial_recurrence_occurrences.c.scheduled_date,
    postgresql_where=text("status = 'PENDING'"),
)

__all__ = ["financial_recurrence_occurrences", "financial_recurrences"]
