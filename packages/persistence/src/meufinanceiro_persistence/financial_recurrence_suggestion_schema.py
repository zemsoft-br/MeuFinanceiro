"""SQLAlchemy metadata for the decisions about derived recurrence suggestions.

A suggestion is never stored. Only the user's explicit, append-only decision is:
``DISMISSED`` (personal) or ``ACCEPTED`` (provenance of the recurrence created in the
same transaction). See ADR-0028.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from meufinanceiro_persistence.schema import metadata

_UUID4 = "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'"

financial_recurrence_suggestion_decisions = Table(
    "recurrence_suggestion_decisions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("account_id", UUID(as_uuid=True), nullable=False),
    Column("operator_id", UUID(as_uuid=True), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("fingerprint", String(64), nullable=False),
    Column("decision", String(16), nullable=False),
    Column("recurrence_id", UUID(as_uuid=True), nullable=True),
    Column("evidence_digest", String(64), nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        f"id::text ~ {_UUID4}", name="ck_finance_recurrence_decisions_id_uuid4"
    ),
    CheckConstraint(
        "decision IN ('ACCEPTED', 'DISMISSED')",
        name="ck_finance_recurrence_decisions_decision",
    ),
    CheckConstraint(
        "(decision = 'ACCEPTED') = (recurrence_id IS NOT NULL)",
        name="ck_finance_recurrence_decisions_shape",
    ),
    ForeignKeyConstraint(
        ["residence_id", "installation_id"],
        ["household.residences.id", "household.residences.installation_id"],
        ondelete="RESTRICT",
        name="fk_finance_recurrence_decisions_residence",
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
        name="fk_finance_recurrence_decisions_account",
    ),
    ForeignKeyConstraint(
        ["recurrence_id", "installation_id", "residence_id"],
        [
            "finance.recurrences.id",
            "finance.recurrences.installation_id",
            "finance.recurrences.residence_id",
        ],
        ondelete="RESTRICT",
        name="fk_finance_recurrence_decisions_recurrence",
    ),
    UniqueConstraint(
        "installation_id",
        "operator_id",
        "fingerprint",
        name="uq_finance_recurrence_decisions_operator_fingerprint",
    ),
    UniqueConstraint(
        "recurrence_id", name="uq_finance_recurrence_decisions_recurrence"
    ),
    schema="finance",
)

Index(
    "ix_finance_recurrence_decisions_account",
    financial_recurrence_suggestion_decisions.c.residence_id,
    financial_recurrence_suggestion_decisions.c.account_id,
)

__all__ = ["financial_recurrence_suggestion_decisions"]
