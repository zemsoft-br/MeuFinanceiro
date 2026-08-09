"""SQLAlchemy metadata for canonical reconciliation of banking transaction observations."""

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
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from meufinanceiro_persistence.banking_observation_schema import external_observations
from meufinanceiro_persistence.schema import metadata

# The reconciliation source relation scopes a local observation UUID to its trusted
# connection/residence. The migration adds the same candidate key in PostgreSQL.
UniqueConstraint(
    external_observations.c.id,
    external_observations.c.connection_id,
    external_observations.c.residence_id,
    name="uq_external_observations_local_scope",
)

reconciled_transactions = Table(
    "reconciled_transactions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("connection_id", UUID(as_uuid=True), nullable=False),
    Column("external_account_record_id", UUID(as_uuid=True), nullable=False),
    Column("identity_kind", String(16), nullable=False),
    Column("identity_digest", String(64), nullable=False),
    Column("status", String(16), nullable=False),
    Column("source_observation_id", UUID(as_uuid=True), nullable=False),
    Column("source_observed_at", DateTime(timezone=True), nullable=False),
    Column("first_reconciled_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "identity_kind IN ('PROVIDER_ID', 'FINGERPRINT')",
        name="ck_reconciled_transactions_identity_kind",
    ),
    CheckConstraint(
        "identity_digest ~ '^[0-9a-f]{64}$'",
        name="ck_reconciled_transactions_identity_digest",
    ),
    CheckConstraint(
        "status IN ('PENDING', 'CONFIRMED', 'INFERRED', 'DELETED')",
        name="ck_reconciled_transactions_status",
    ),
    ForeignKeyConstraint(
        ["external_account_record_id", "connection_id", "residence_id"],
        [
            "integrations.external_accounts.id",
            "integrations.external_accounts.connection_id",
            "integrations.external_accounts.residence_id",
        ],
        ondelete="RESTRICT",
        name="fk_reconciled_transactions_account_scope",
    ),
    ForeignKeyConstraint(
        ["source_observation_id", "connection_id", "residence_id"],
        [
            "integrations.external_observations.id",
            "integrations.external_observations.connection_id",
            "integrations.external_observations.residence_id",
        ],
        ondelete="RESTRICT",
        name="fk_reconciled_transactions_source_scope",
    ),
    UniqueConstraint(
        "id",
        "connection_id",
        "residence_id",
        name="uq_reconciled_transactions_scope",
    ),
    UniqueConstraint(
        "connection_id",
        "external_account_record_id",
        "identity_kind",
        "identity_digest",
        name="uq_reconciled_transactions_identity",
    ),
    schema="integrations",
)

Index(
    "ix_reconciled_transactions_account_status",
    reconciled_transactions.c.residence_id,
    reconciled_transactions.c.connection_id,
    reconciled_transactions.c.external_account_record_id,
    reconciled_transactions.c.status,
)

reconciled_transaction_sources = Table(
    "reconciled_transaction_sources",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("connection_id", UUID(as_uuid=True), nullable=False),
    Column("reconciled_transaction_id", UUID(as_uuid=True), nullable=False),
    Column("source_observation_id", UUID(as_uuid=True), nullable=False),
    Column("observation_updated_at", DateTime(timezone=True), nullable=False),
    Column("first_reconciled_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["reconciled_transaction_id", "connection_id", "residence_id"],
        [
            "integrations.reconciled_transactions.id",
            "integrations.reconciled_transactions.connection_id",
            "integrations.reconciled_transactions.residence_id",
        ],
        ondelete="CASCADE",
        name="fk_reconciled_transaction_sources_target_scope",
    ),
    ForeignKeyConstraint(
        ["source_observation_id", "connection_id", "residence_id"],
        [
            "integrations.external_observations.id",
            "integrations.external_observations.connection_id",
            "integrations.external_observations.residence_id",
        ],
        ondelete="RESTRICT",
        name="fk_reconciled_transaction_sources_observation_scope",
    ),
    UniqueConstraint(
        "source_observation_id",
        "connection_id",
        "residence_id",
        name="uq_reconciled_transaction_sources_observation",
    ),
    schema="integrations",
)

Index(
    "ix_reconciled_transaction_sources_target",
    reconciled_transaction_sources.c.residence_id,
    reconciled_transaction_sources.c.connection_id,
    reconciled_transaction_sources.c.reconciled_transaction_id,
)

DIRTY_RECONCILIATION_PREDICATE = text(
    "reconciled_transaction_sources.id IS NULL OR "
    "reconciled_transaction_sources.observation_updated_at < external_observations.updated_at"
)
