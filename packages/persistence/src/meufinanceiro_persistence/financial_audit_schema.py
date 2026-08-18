"""SQLAlchemy metadata for append-only financial audit events."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from meufinanceiro_persistence.schema import metadata

financial_audit_events = Table(
    "audit_events",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("actor_operator_id", UUID(as_uuid=True), nullable=False),
    Column("event_type", String(32), nullable=False),
    Column("subject_type", String(24), nullable=False),
    Column("subject_id", UUID(as_uuid=True), nullable=False),
    Column("related_subject_type", String(24), nullable=True),
    Column("related_subject_id", UUID(as_uuid=True), nullable=True),
    Column("event_schema_version", SmallInteger, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "id::text ~ "
        "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
        name="ck_finance_audit_events_id_uuid4",
    ),
    CheckConstraint(
        "event_type IN ("
        "'ACCOUNT_CREATED', 'CATEGORY_CREATED', 'OPENING_BALANCE_CREATED', "
        "'MOVEMENT_CREATED', 'MOVEMENT_REVERSED', 'TRANSFER_CREATED', "
        "'TRANSFER_REVERSED', 'ALLOCATION_SET_CREATED', 'ALLOCATION_SET_REVISED')",
        name="ck_finance_audit_events_event_type",
    ),
    CheckConstraint(
        "subject_type IN ("
        "'ACCOUNT', 'CATEGORY', 'OPENING_BALANCE', 'MOVEMENT', 'TRANSFER', "
        "'ALLOCATION_SET')",
        name="ck_finance_audit_events_subject_type",
    ),
    CheckConstraint(
        "related_subject_type IS NULL OR related_subject_type IN ("
        "'MOVEMENT', 'TRANSFER', 'ALLOCATION_SET')",
        name="ck_finance_audit_events_related_subject_type",
    ),
    CheckConstraint(
        "event_schema_version = 1",
        name="ck_finance_audit_events_schema_version",
    ),
    CheckConstraint(
        "(event_type = 'ACCOUNT_CREATED' AND subject_type = 'ACCOUNT' "
        "AND related_subject_type IS NULL AND related_subject_id IS NULL) OR "
        "(event_type = 'CATEGORY_CREATED' AND subject_type = 'CATEGORY' "
        "AND related_subject_type IS NULL AND related_subject_id IS NULL) OR "
        "(event_type = 'OPENING_BALANCE_CREATED' "
        "AND subject_type = 'OPENING_BALANCE' "
        "AND related_subject_type IS NULL AND related_subject_id IS NULL) OR "
        "(event_type = 'MOVEMENT_CREATED' AND subject_type = 'MOVEMENT' "
        "AND related_subject_type IS NULL AND related_subject_id IS NULL) OR "
        "(event_type = 'MOVEMENT_REVERSED' AND subject_type = 'MOVEMENT' "
        "AND related_subject_type = 'MOVEMENT' AND related_subject_id IS NOT NULL) OR "
        "(event_type = 'TRANSFER_CREATED' AND subject_type = 'TRANSFER' "
        "AND related_subject_type IS NULL AND related_subject_id IS NULL) OR "
        "(event_type = 'TRANSFER_REVERSED' AND subject_type = 'TRANSFER' "
        "AND related_subject_type = 'TRANSFER' AND related_subject_id IS NOT NULL) OR "
        "(event_type = 'ALLOCATION_SET_CREATED' "
        "AND subject_type = 'ALLOCATION_SET' "
        "AND related_subject_type IS NULL AND related_subject_id IS NULL) OR "
        "(event_type = 'ALLOCATION_SET_REVISED' "
        "AND subject_type = 'ALLOCATION_SET' "
        "AND related_subject_type = 'ALLOCATION_SET' "
        "AND related_subject_id IS NOT NULL)",
        name="ck_finance_audit_events_event_subject_shape",
    ),
    CheckConstraint(
        "related_subject_id IS NULL OR related_subject_id <> subject_id",
        name="ck_finance_audit_events_distinct_related",
    ),
    ForeignKeyConstraint(
        ["residence_id", "actor_operator_id"],
        ["household.memberships.residence_id", "household.memberships.operator_id"],
        ondelete="RESTRICT",
        name="fk_finance_audit_events_actor_membership",
    ),
    UniqueConstraint(
        "subject_type",
        "subject_id",
        name="uq_finance_audit_events_subject",
    ),
    schema="finance",
)

Index(
    "ix_finance_audit_events_actor_time",
    financial_audit_events.c.residence_id,
    financial_audit_events.c.actor_operator_id,
    financial_audit_events.c.occurred_at,
    financial_audit_events.c.id,
)

__all__ = ["financial_audit_events"]
