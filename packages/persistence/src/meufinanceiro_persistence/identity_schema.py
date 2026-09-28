"""SQLAlchemy Core tables for local operator authentication."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from meufinanceiro_persistence import schema as _shared_schema

metadata = _shared_schema.metadata

identity_installation = Table(
    "installation",
    metadata,
    Column("singleton", Boolean, primary_key=True),
    Column("id", UUID(as_uuid=True), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("singleton", name="ck_identity_installation_singleton"),
    schema="identity",
)

identity_operators = Table(
    "operators",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "installation_id",
        UUID(as_uuid=True),
        ForeignKey(
            "identity.installation.id",
            name="fk_identity_operators_installation",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("login_name", String(64), nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("role", String(32), nullable=False),
    Column("status", String(16), nullable=False),
    Column("failed_attempts", Integer, nullable=False),
    Column("locked_until", DateTime(timezone=True), nullable=True),
    Column("last_authenticated_at", DateTime(timezone=True), nullable=True),
    Column("password_changed_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "login_name ~ '^[a-z0-9][a-z0-9._-]{2,63}$'",
        name="ck_identity_operators_login",
    ),
    CheckConstraint(
        "role = 'installation_admin'",
        name="ck_identity_operators_role",
    ),
    CheckConstraint(
        "status IN ('active', 'disabled')",
        name="ck_identity_operators_status",
    ),
    CheckConstraint(
        "failed_attempts >= 0",
        name="ck_identity_operators_failed_attempts",
    ),
    CheckConstraint(
        "length(password_hash) BETWEEN 32 AND 1024",
        name="ck_identity_operators_password_hash_length",
    ),
    UniqueConstraint("login_name", name="uq_identity_operators_login"),
    UniqueConstraint(
        "id",
        "installation_id",
        name="uq_identity_operators_installation_scope",
    ),
    schema="identity",
)

identity_sessions = Table(
    "sessions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("operator_id", UUID(as_uuid=True), nullable=False),
    Column("token_hash", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    CheckConstraint(
        "token_hash ~ '^[0-9a-f]{64}$'",
        name="ck_identity_sessions_token_hash",
    ),
    CheckConstraint(
        "expires_at > created_at",
        name="ck_identity_sessions_expiration",
    ),
    CheckConstraint(
        "last_seen_at >= created_at",
        name="ck_identity_sessions_last_seen",
    ),
    CheckConstraint(
        "revoked_at IS NULL OR revoked_at >= created_at",
        name="ck_identity_sessions_revoked_at",
    ),
    ForeignKeyConstraint(
        ["operator_id", "installation_id"],
        ["identity.operators.id", "identity.operators.installation_id"],
        ondelete="CASCADE",
        name="fk_identity_sessions_operator_scope",
    ),
    UniqueConstraint("token_hash", name="uq_identity_sessions_token_hash"),
    schema="identity",
)

Index(
    "ix_identity_sessions_operator_expiration",
    identity_sessions.c.operator_id,
    identity_sessions.c.expires_at,
)

setattr(_shared_schema, "identity_installation", identity_installation)
setattr(_shared_schema, "identity_operators", identity_operators)
setattr(_shared_schema, "identity_sessions", identity_sessions)
