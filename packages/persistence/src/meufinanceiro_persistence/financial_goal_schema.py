"""SQLAlchemy metadata for financial goals (planning, never a ledger).

``finance.goals`` carries the identity (audience, owner, currency) and the planning
data under a CAS ``version``. ``finance.goal_allocation_events`` is the append-only
history of explicit virtual ``ALLOCATE`` (positive) / ``RELEASE`` (negative) events:
what a goal holds is always their sum. Nothing here is a Movement, a balance or an
allocated amount (ADR-0029).
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

financial_goals = Table(
    "goals",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("owner_operator_id", UUID(as_uuid=True), nullable=False),
    Column("visibility_scope", String(16), nullable=False),
    Column("title", String(96), nullable=False),
    Column("description", String(280)),
    Column("currency", String(3), nullable=False),
    Column("target_amount", Numeric(24, 8), nullable=False),
    Column("target_date", Date()),
    Column("version", Integer(), nullable=False),
    Column("idempotency_key", UUID(as_uuid=True), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("updated_by_operator_id", UUID(as_uuid=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(f"id::text ~ {_UUID4}", name="ck_finance_goals_id_uuid4"),
    CheckConstraint(
        f"idempotency_key::text ~ {_UUID4}",
        name="ck_finance_goals_idempotency_uuid4",
    ),
    CheckConstraint(
        "visibility_scope IN ('PERSONAL', 'HOUSEHOLD')",
        name="ck_finance_goals_scope",
    ),
    CheckConstraint(
        "length(btrim(title)) BETWEEN 1 AND 96", name="ck_finance_goals_title"
    ),
    CheckConstraint(
        "description IS NULL OR length(btrim(description)) BETWEEN 1 AND 280",
        name="ck_finance_goals_description",
    ),
    CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_finance_goals_currency"),
    CheckConstraint(
        "target_amount > 0 AND target_amount::text NOT IN "
        "('NaN', 'Infinity', '-Infinity')",
        name="ck_finance_goals_target_positive",
    ),
    CheckConstraint("version >= 1", name="ck_finance_goals_version"),
    CheckConstraint(
        "request_digest ~ '^[0-9a-f]{64}$'", name="ck_finance_goals_request_digest"
    ),
    CheckConstraint("updated_at >= created_at", name="ck_finance_goals_timestamps"),
    ForeignKeyConstraint(
        ["residence_id", "installation_id"],
        ["household.residences.id", "household.residences.installation_id"],
        ondelete="RESTRICT",
        name="fk_finance_goals_residence",
    ),
    ForeignKeyConstraint(
        ["residence_id", "owner_operator_id"],
        ["household.memberships.residence_id", "household.memberships.operator_id"],
        ondelete="RESTRICT",
        name="fk_finance_goals_owner_membership",
    ),
    ForeignKeyConstraint(
        ["residence_id", "updated_by_operator_id"],
        ["household.memberships.residence_id", "household.memberships.operator_id"],
        ondelete="RESTRICT",
        name="fk_finance_goals_updater_membership",
    ),
    UniqueConstraint(
        "id",
        "installation_id",
        "residence_id",
        "currency",
        name="uq_finance_goals_scope",
    ),
    UniqueConstraint(
        "installation_id", "idempotency_key", name="uq_finance_goals_idempotency"
    ),
    schema="finance",
)

financial_goal_allocation_events = Table(
    "goal_allocation_events",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("goal_id", UUID(as_uuid=True), nullable=False),
    Column("account_id", UUID(as_uuid=True), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("kind", String(16), nullable=False),
    Column("amount", Numeric(24, 8), nullable=False),
    Column("actor_operator_id", UUID(as_uuid=True), nullable=False),
    Column("idempotency_key", UUID(as_uuid=True), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(f"id::text ~ {_UUID4}", name="ck_finance_goal_events_id_uuid4"),
    CheckConstraint(
        f"idempotency_key::text ~ {_UUID4}",
        name="ck_finance_goal_events_idempotency_uuid4",
    ),
    CheckConstraint(
        "kind IN ('ALLOCATE', 'RELEASE')", name="ck_finance_goal_events_kind"
    ),
    CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_finance_goal_events_currency"),
    CheckConstraint(
        "amount::text NOT IN ('NaN', 'Infinity', '-Infinity') AND "
        "((kind = 'ALLOCATE' AND amount > 0) OR (kind = 'RELEASE' AND amount < 0))",
        name="ck_finance_goal_events_amount_sign",
    ),
    CheckConstraint(
        "request_digest ~ '^[0-9a-f]{64}$'",
        name="ck_finance_goal_events_request_digest",
    ),
    ForeignKeyConstraint(
        ["goal_id", "installation_id", "residence_id", "currency"],
        [
            "finance.goals.id",
            "finance.goals.installation_id",
            "finance.goals.residence_id",
            "finance.goals.currency",
        ],
        ondelete="RESTRICT",
        name="fk_finance_goal_events_goal",
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
        name="fk_finance_goal_events_account",
    ),
    ForeignKeyConstraint(
        ["residence_id", "actor_operator_id"],
        ["household.memberships.residence_id", "household.memberships.operator_id"],
        ondelete="RESTRICT",
        name="fk_finance_goal_events_actor_membership",
    ),
    UniqueConstraint(
        "installation_id",
        "idempotency_key",
        name="uq_finance_goal_events_idempotency",
    ),
    schema="finance",
)

Index(
    "ix_finance_goals_owner",
    financial_goals.c.residence_id,
    financial_goals.c.owner_operator_id,
    financial_goals.c.created_at,
    financial_goals.c.id,
)
Index(
    "ix_finance_goal_events_goal",
    financial_goal_allocation_events.c.goal_id,
    financial_goal_allocation_events.c.created_at,
    financial_goal_allocation_events.c.id,
)
Index(
    "ix_finance_goal_events_account",
    financial_goal_allocation_events.c.account_id,
    postgresql_include=["amount"],
)

__all__ = ["financial_goal_allocation_events", "financial_goals"]
