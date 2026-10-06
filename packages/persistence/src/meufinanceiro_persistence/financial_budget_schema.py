"""SQLAlchemy metadata for monthly category budgets (planning, never a ledger).

``finance.budgets`` carries the identity (scope, owner, currency, month, date
basis) and the CAS ``version``. ``finance.budget_lines`` is append-only: every
version owns a complete set of lines (``revision``) and the current lines are the
ones whose ``revision`` equals ``budgets.version``. Nothing here holds a Movement,
a balance or a realized amount.
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
)
from sqlalchemy.dialects.postgresql import UUID

from meufinanceiro_persistence.schema import metadata

_UUID4 = "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'"

financial_budgets = Table(
    "budgets",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("owner_operator_id", UUID(as_uuid=True), nullable=False),
    Column("visibility_scope", String(16), nullable=False),
    Column("name", String(96), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("period_kind", String(16), nullable=False),
    Column("period_start", Date(), nullable=False),
    Column("date_basis", String(16), nullable=False),
    Column("version", Integer(), nullable=False),
    Column("idempotency_key", UUID(as_uuid=True), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("updated_by_operator_id", UUID(as_uuid=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(f"id::text ~ {_UUID4}", name="ck_finance_budgets_id_uuid4"),
    CheckConstraint(
        f"idempotency_key::text ~ {_UUID4}",
        name="ck_finance_budgets_idempotency_uuid4",
    ),
    CheckConstraint(
        "visibility_scope IN ('PERSONAL', 'HOUSEHOLD')",
        name="ck_finance_budgets_scope",
    ),
    CheckConstraint(
        "length(btrim(name)) BETWEEN 1 AND 96", name="ck_finance_budgets_name"
    ),
    CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_finance_budgets_currency"),
    CheckConstraint("period_kind = 'MONTHLY'", name="ck_finance_budgets_period_kind"),
    CheckConstraint(
        "EXTRACT(DAY FROM period_start) = 1", name="ck_finance_budgets_period_start"
    ),
    CheckConstraint(
        "date_basis IN ('CASH', 'COMPETENCE')", name="ck_finance_budgets_date_basis"
    ),
    CheckConstraint("version >= 1", name="ck_finance_budgets_version"),
    CheckConstraint(
        "request_digest ~ '^[0-9a-f]{64}$'", name="ck_finance_budgets_request_digest"
    ),
    CheckConstraint("updated_at >= created_at", name="ck_finance_budgets_timestamps"),
    ForeignKeyConstraint(
        ["residence_id", "installation_id"],
        ["household.residences.id", "household.residences.installation_id"],
        ondelete="RESTRICT",
        name="fk_finance_budgets_residence",
    ),
    ForeignKeyConstraint(
        ["residence_id", "owner_operator_id"],
        ["household.memberships.residence_id", "household.memberships.operator_id"],
        ondelete="RESTRICT",
        name="fk_finance_budgets_owner_membership",
    ),
    ForeignKeyConstraint(
        ["residence_id", "updated_by_operator_id"],
        ["household.memberships.residence_id", "household.memberships.operator_id"],
        ondelete="RESTRICT",
        name="fk_finance_budgets_updater_membership",
    ),
    UniqueConstraint(
        "id", "installation_id", "residence_id", name="uq_finance_budgets_scope"
    ),
    UniqueConstraint(
        "installation_id", "idempotency_key", name="uq_finance_budgets_idempotency"
    ),
    schema="finance",
)

financial_budget_lines = Table(
    "budget_lines",
    metadata,
    Column("budget_id", UUID(as_uuid=True), primary_key=True),
    Column("revision", Integer(), primary_key=True),
    Column("category_id", UUID(as_uuid=True), primary_key=True),
    Column("result_effect", String(16), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("planned_amount", Numeric(24, 8), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("revision >= 1", name="ck_finance_budget_lines_revision"),
    CheckConstraint(
        "result_effect IN ('INCOME', 'EXPENSE')",
        name="ck_finance_budget_lines_effect",
    ),
    CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_finance_budget_lines_currency"),
    CheckConstraint(
        "planned_amount > 0 AND planned_amount::text NOT IN "
        "('NaN', 'Infinity', '-Infinity')",
        name="ck_finance_budget_lines_planned_positive",
    ),
    ForeignKeyConstraint(
        ["budget_id", "installation_id", "residence_id"],
        [
            "finance.budgets.id",
            "finance.budgets.installation_id",
            "finance.budgets.residence_id",
        ],
        ondelete="RESTRICT",
        name="fk_finance_budget_lines_budget",
    ),
    ForeignKeyConstraint(
        ["category_id"],
        ["finance.categories.id"],
        ondelete="RESTRICT",
        name="fk_finance_budget_lines_category",
    ),
    schema="finance",
)

Index(
    "ix_finance_budgets_period",
    financial_budgets.c.residence_id,
    financial_budgets.c.period_start,
    financial_budgets.c.visibility_scope,
    financial_budgets.c.id,
)
Index(
    "ix_finance_budget_lines_category",
    financial_budget_lines.c.residence_id,
    financial_budget_lines.c.category_id,
)

__all__ = ["financial_budget_lines", "financial_budgets"]
