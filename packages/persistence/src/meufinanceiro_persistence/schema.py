"""SQLAlchemy Core metadata shared by persistence operations and migrations."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

task_queue = Table(
    "task_queue",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("task_type", String(100), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("status", String(16), nullable=False),
    Column("idempotency_key", String(200), nullable=False),
    Column("correlation_id", UUID(as_uuid=True), nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("max_attempts", Integer, nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("locked_at", DateTime(timezone=True), nullable=True),
    Column("lease_expires_at", DateTime(timezone=True), nullable=True),
    Column("locked_by", String(200), nullable=True),
    Column("lease_token", UUID(as_uuid=True), nullable=True),
    Column("last_error", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    CheckConstraint(
        "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
        name="ck_task_queue_status",
    ),
    CheckConstraint("attempts >= 0", name="ck_task_queue_attempts_nonnegative"),
    CheckConstraint("max_attempts > 0", name="ck_task_queue_max_attempts_positive"),
    CheckConstraint(
        "(status = 'running' AND locked_at IS NOT NULL AND lease_expires_at IS NOT NULL "
        "AND locked_by IS NOT NULL AND lease_token IS NOT NULL) OR "
        "(status <> 'running' AND locked_at IS NULL AND lease_expires_at IS NULL "
        "AND locked_by IS NULL AND lease_token IS NULL)",
        name="ck_task_queue_lease_state",
    ),
    CheckConstraint(
        "(status IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NOT NULL) OR "
        "(status NOT IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NULL)",
        name="ck_task_queue_completion_state",
    ),
    UniqueConstraint("idempotency_key", name="uq_task_queue_idempotency_key"),
    schema="infra",
)

Index(
    "ix_task_queue_claimable",
    task_queue.c.status,
    task_queue.c.available_at,
    task_queue.c.created_at,
)


demo_task_effects = Table(
    "demo_task_effects",
    metadata,
    Column(
        "task_id",
        UUID(as_uuid=True),
        ForeignKey("infra.task_queue.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("message", String(500), nullable=False),
    schema="infra",
)


demo_fixture = Table(
    "demo_fixture",
    metadata,
    Column("fixture_id", String(100), primary_key=True),
    Column("fixture_version", Integer, nullable=False),
    Column("reference_date", Date, nullable=False),
    Column("timezone", String(64), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("scope", String(64), nullable=False),
    Column("contract_checksum", String(64), nullable=False),
    Column("loaded_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("fixture_version > 0", name="ck_demo_fixture_version_positive"),
    CheckConstraint(
        "contract_checksum ~ '^[0-9a-f]{64}$'",
        name="ck_demo_fixture_checksum_sha256",
    ),
    schema="infra",
)


provider_configurations = Table(
    "provider_configurations",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("provider", String(64), nullable=False),
    Column("state", String(16), nullable=False),
    Column("client_id_envelope", Text, nullable=True),
    Column("client_secret_envelope", Text, nullable=True),
    Column("configuration_revision", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("enabled_at", DateTime(timezone=True), nullable=True),
    Column("disabled_at", DateTime(timezone=True), nullable=True),
    CheckConstraint(
        "provider ~ '^[a-z][a-z0-9_]{0,62}$'",
        name="ck_provider_configurations_provider",
    ),
    CheckConstraint(
        "state IN ('disabled', 'configured', 'enabled')",
        name="ck_provider_configurations_state",
    ),
    CheckConstraint(
        "configuration_revision > 0",
        name="ck_provider_configurations_revision_positive",
    ),
    CheckConstraint(
        "(client_id_envelope IS NULL) = (client_secret_envelope IS NULL)",
        name="ck_provider_configurations_envelopes_paired",
    ),
    CheckConstraint(
        "state = 'disabled' OR "
        "(client_id_envelope IS NOT NULL AND client_secret_envelope IS NOT NULL)",
        name="ck_provider_configurations_state_credentials",
    ),
    CheckConstraint(
        "state <> 'enabled' OR enabled_at IS NOT NULL",
        name="ck_provider_configurations_enabled_at",
    ),
    UniqueConstraint(
        "installation_id",
        "provider",
        name="uq_provider_configurations_installation_provider",
    ),
    UniqueConstraint(
        "id",
        "installation_id",
        "provider",
        name="uq_provider_configurations_scope",
    ),
    schema="integrations",
)


connections = Table(
    "connections",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("installation_id", UUID(as_uuid=True), nullable=False),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("provider", String(64), nullable=False),
    Column("provider_configuration_id", UUID(as_uuid=True), nullable=False),
    Column("external_connection_id", String(512), nullable=False),
    Column("status", String(32), nullable=False),
    Column("requires_user_action", Boolean, nullable=False),
    Column("last_successful_sync_at", DateTime(timezone=True), nullable=True),
    Column("last_attempt_at", DateTime(timezone=True), nullable=True),
    Column("next_refresh_allowed_at", DateTime(timezone=True), nullable=True),
    Column("consent_expires_at", DateTime(timezone=True), nullable=True),
    Column("provider_reason_code", String(128), nullable=True),
    Column("disconnected_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "provider ~ '^[a-z][a-z0-9_]{0,62}$'",
        name="ck_connections_provider",
    ),
    CheckConstraint(
        "status IN ("
        "'PENDING_USER_ACTION', 'SYNC_REQUESTED', 'SYNCING', 'AVAILABLE', "
        "'PARTIAL', 'REAUTHENTICATION_REQUIRED', 'TEMPORARILY_UNAVAILABLE', "
        "'RATE_LIMITED', 'DISCONNECTED', 'FAILED')",
        name="ck_connections_status",
    ),
    CheckConstraint(
        "provider_reason_code IS NULL OR "
        "provider_reason_code ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'",
        name="ck_connections_provider_reason_code",
    ),
    CheckConstraint(
        "status NOT IN ('PENDING_USER_ACTION', 'REAUTHENTICATION_REQUIRED') "
        "OR requires_user_action",
        name="ck_connections_required_user_action",
    ),
    CheckConstraint(
        "status <> 'DISCONNECTED' OR "
        "(NOT requires_user_action AND disconnected_at IS NOT NULL)",
        name="ck_connections_disconnected_state",
    ),
    ForeignKeyConstraint(
        ["provider_configuration_id", "installation_id", "provider"],
        [
            "integrations.provider_configurations.id",
            "integrations.provider_configurations.installation_id",
            "integrations.provider_configurations.provider",
        ],
        ondelete="RESTRICT",
        name="fk_connections_provider_configuration_scope",
    ),
    UniqueConstraint(
        "installation_id",
        "provider",
        "external_connection_id",
        name="uq_connections_external",
    ),
    UniqueConstraint(
        "id",
        "residence_id",
        name="uq_connections_residence_scope",
    ),
    schema="integrations",
)

Index(
    "ix_connections_residence_status",
    connections.c.residence_id,
    connections.c.status,
)


connection_capabilities = Table(
    "connection_capabilities",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("connection_id", UUID(as_uuid=True), nullable=False),
    Column("capability", String(64), nullable=False),
    Column("state", String(32), nullable=False),
    Column("source", String(16), nullable=False),
    Column("provider_reason_code", String(128), nullable=True),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "capability IN ("
        "'identity', 'bank_accounts', 'credit_accounts', 'transactions', "
        "'credit_card_bills', 'investments', 'loans', 'manual_refresh', "
        "'consent_renewal', 'disconnect', 'webhooks')",
        name="ck_connection_capabilities_capability",
    ),
    CheckConstraint(
        "state IN ("
        "'SUPPORTED', 'NOT_AVAILABLE', 'REQUIRES_USER_ACTION', "
        "'NOT_OBSERVED', 'UNKNOWN')",
        name="ck_connection_capabilities_state",
    ),
    CheckConstraint(
        "source IN ('CONTRACT', 'OBSERVATION', 'OPERATION')",
        name="ck_connection_capabilities_source",
    ),
    CheckConstraint(
        "provider_reason_code IS NULL OR "
        "provider_reason_code ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'",
        name="ck_connection_capabilities_provider_reason_code",
    ),
    ForeignKeyConstraint(
        ["connection_id", "residence_id"],
        [
            "integrations.connections.id",
            "integrations.connections.residence_id",
        ],
        ondelete="CASCADE",
        name="fk_connection_capabilities_connection_scope",
    ),
    UniqueConstraint(
        "connection_id",
        "capability",
        name="uq_connection_capabilities_connection_capability",
    ),
    schema="integrations",
)

Index(
    "ix_connection_capabilities_residence_connection",
    connection_capabilities.c.residence_id,
    connection_capabilities.c.connection_id,
)
