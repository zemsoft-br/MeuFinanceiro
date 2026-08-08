"""SQLAlchemy metadata for normalized external banking observations."""

from __future__ import annotations

from sqlalchemy import (
    CHAR,
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

external_observations = Table(
    "external_observations",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("connection_id", UUID(as_uuid=True), nullable=False),
    Column("external_account_id", String(512), nullable=False),
    Column("resource_type", String(32), nullable=False),
    Column("external_resource_id", String(512), nullable=True),
    Column("status", String(16), nullable=False),
    Column("provider_updated_at", DateTime(timezone=True), nullable=True),
    Column("effective_date", Date, nullable=False),
    Column("amount", Numeric(24, 8), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("description", String(512), nullable=True),
    Column("category", String(128), nullable=True),
    Column("stable_fingerprint", CHAR(64), nullable=False),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("deleted_at", DateTime(timezone=True), nullable=True),
    Column("normalized_payload_version", Integer, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("resource_type = 'transactions'", name="ck_external_observations_resource"),
    CheckConstraint(
        "status IN ('CONFIRMED', 'PENDING', 'INFERRED', 'DELETED')",
        name="ck_external_observations_status",
    ),
    CheckConstraint(
        "external_resource_id IS NULL OR ("
        "length(external_resource_id) BETWEEN 1 AND 512 AND "
        "external_resource_id = btrim(external_resource_id) AND "
        "external_resource_id !~ '[[:cntrl:]]')",
        name="ck_external_observations_external_id_shape",
    ),
    CheckConstraint(
        "status <> 'INFERRED' OR external_resource_id IS NULL",
        name="ck_external_observations_inferred_identity",
    ),
    CheckConstraint(
        "amount::text NOT IN ('NaN', 'Infinity', '-Infinity')",
        name="ck_external_observations_amount_finite",
    ),
    CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_external_observations_currency"),
    CheckConstraint(
        "description IS NULL OR (length(description) BETWEEN 1 AND 512 AND "
        "description = btrim(description) AND description !~ '[[:cntrl:]]')",
        name="ck_external_observations_description_shape",
    ),
    CheckConstraint(
        "category IS NULL OR (length(category) BETWEEN 1 AND 128 AND "
        "category = btrim(category) AND category !~ '[[:cntrl:]]')",
        name="ck_external_observations_category_shape",
    ),
    CheckConstraint(
        "stable_fingerprint ~ '^[0-9a-f]{64}$'",
        name="ck_external_observations_fingerprint",
    ),
    CheckConstraint("last_seen_at >= first_seen_at", name="ck_external_observations_seen_order"),
    CheckConstraint(
        "(status = 'DELETED' AND deleted_at IS NOT NULL) OR "
        "(status <> 'DELETED' AND deleted_at IS NULL)",
        name="ck_external_observations_deleted_state",
    ),
    CheckConstraint(
        "normalized_payload_version = 1",
        name="ck_external_observations_payload_version",
    ),
    ForeignKeyConstraint(
        ["connection_id", "residence_id", "external_account_id"],
        [
            "integrations.external_accounts.connection_id",
            "integrations.external_accounts.residence_id",
            "integrations.external_accounts.external_account_id",
        ],
        ondelete="RESTRICT",
        name="fk_external_observations_account_scope",
    ),
    UniqueConstraint(
        "connection_id",
        "external_account_id",
        "stable_fingerprint",
        name="uq_external_observations_fingerprint",
    ),
    schema="integrations",
)

Index(
    "uq_external_observations_external_resource",
    external_observations.c.connection_id,
    external_observations.c.external_account_id,
    external_observations.c.external_resource_id,
    unique=True,
    postgresql_where=text("external_resource_id IS NOT NULL"),
)
Index(
    "ix_external_observations_residence_account_date",
    external_observations.c.residence_id,
    external_observations.c.connection_id,
    external_observations.c.external_account_id,
    external_observations.c.effective_date,
)
