"""SQLAlchemy Core tables for residences and operator memberships."""

from sqlalchemy import (
    Boolean,
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

from meufinanceiro_persistence import schema as _shared_schema

metadata = _shared_schema.metadata

household_residences = Table(
    "residences",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("name", String(96), nullable=False),
    Column("status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "length(btrim(name)) BETWEEN 1 AND 96",
        name="ck_household_residences_name",
    ),
    CheckConstraint(
        "status IN ('active', 'archived')",
        name="ck_household_residences_status",
    ),
    ForeignKeyConstraint(
        ["installation_id"],
        ["identity.installation.id"],
        ondelete="RESTRICT",
        name="fk_household_residences_installation",
    ),
    UniqueConstraint(
        "id",
        "installation_id",
        name="uq_household_residences_installation_scope",
    ),
    schema="household",
)

Index(
    "ix_household_residences_installation_status",
    household_residences.c.installation_id,
    household_residences.c.status,
)

_shared_schema.connections.append_constraint(
    ForeignKeyConstraint(
        ["residence_id", "installation_id"],
        ["household.residences.id", "household.residences.installation_id"],
        ondelete="RESTRICT",
        name="fk_connections_household_residence_scope",
    )
)

household_memberships = Table(
    "memberships",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("operator_id", UUID(as_uuid=True), nullable=False),
    Column("role", String(24), nullable=False),
    Column("status", String(16), nullable=False),
    Column("is_primary", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "role IN ('owner', 'administrator', 'member')",
        name="ck_household_memberships_role",
    ),
    CheckConstraint(
        "status IN ('active', 'disabled')",
        name="ck_household_memberships_status",
    ),
    CheckConstraint(
        "NOT is_primary OR status = 'active'",
        name="ck_household_memberships_primary_active",
    ),
    ForeignKeyConstraint(
        ["residence_id", "installation_id"],
        ["household.residences.id", "household.residences.installation_id"],
        ondelete="RESTRICT",
        name="fk_household_memberships_residence_scope",
    ),
    ForeignKeyConstraint(
        ["operator_id", "installation_id"],
        ["identity.operators.id", "identity.operators.installation_id"],
        ondelete="RESTRICT",
        name="fk_household_memberships_operator_scope",
    ),
    UniqueConstraint(
        "residence_id",
        "operator_id",
        name="uq_household_memberships_residence_operator",
    ),
    schema="household",
)

Index(
    "ix_household_memberships_operator_status",
    household_memberships.c.installation_id,
    household_memberships.c.operator_id,
    household_memberships.c.status,
)
Index(
    "uq_household_memberships_primary_operator",
    household_memberships.c.operator_id,
    unique=True,
    postgresql_where=text("is_primary AND status = 'active'"),
)

setattr(_shared_schema, "household_residences", household_residences)
setattr(_shared_schema, "household_memberships", household_memberships)
