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
    text,
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
    ForeignKeyConstraint(
        ["residence_id", "installation_id"],
        ["household.residences.id", "household.residences.installation_id"],
        ondelete="RESTRICT",
        name="fk_connections_household_residence_scope",
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


sync_runs = Table(
    "sync_runs",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("connection_id", UUID(as_uuid=True), nullable=False),
    Column("idempotency_key", String(200), nullable=False),
    Column("trigger", String(16), nullable=False),
    Column("status", String(16), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("attempt_count", Integer, nullable=False),
    Column("error_category", String(32), nullable=True),
    Column("provider_reason_code", String(128), nullable=True),
    Column("http_status", Integer, nullable=True),
    Column("retry_window_bucket", String(32), nullable=True),
    Column("records_seen", Integer, nullable=False),
    Column("records_applied", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("trigger IN ('manual')", name="ck_sync_runs_trigger"),
    CheckConstraint(
        "status IN ('requested', 'running', 'partial', 'succeeded', 'failed', 'cancelled')",
        name="ck_sync_runs_status",
    ),
    CheckConstraint(
        "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$'",
        name="ck_sync_runs_idempotency_key",
    ),
    CheckConstraint("attempt_count >= 0", name="ck_sync_runs_attempt_count"),
    CheckConstraint("records_seen >= 0", name="ck_sync_runs_records_seen"),
    CheckConstraint("records_applied >= 0", name="ck_sync_runs_records_applied"),
    CheckConstraint(
        "records_applied <= records_seen",
        name="ck_sync_runs_records_applied_seen",
    ),
    CheckConstraint(
        "(status IN ('partial', 'succeeded', 'failed', 'cancelled') AND finished_at IS NOT NULL) OR "
        "(status IN ('requested', 'running') AND finished_at IS NULL)",
        name="ck_sync_runs_finished_at",
    ),
    CheckConstraint(
        "status <> 'running' OR started_at IS NOT NULL",
        name="ck_sync_runs_running_started_at",
    ),
    CheckConstraint(
        "error_category IS NULL OR error_category IN ("
        "'AUTHENTICATION', 'AUTHORIZATION', 'NOT_FOUND', 'INVALID_REQUEST', "
        "'REQUIRES_USER_ACTION', 'RATE_LIMITED', 'TEMPORARILY_UNAVAILABLE', "
        "'CONFLICT', 'UNSUPPORTED', 'INTERNAL')",
        name="ck_sync_runs_error_category",
    ),
    CheckConstraint(
        "provider_reason_code IS NULL OR "
        "provider_reason_code ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'",
        name="ck_sync_runs_provider_reason_code",
    ),
    CheckConstraint(
        "http_status IS NULL OR (http_status >= 100 AND http_status <= 599)",
        name="ck_sync_runs_http_status",
    ),
    CheckConstraint(
        "retry_window_bucket IS NULL OR "
        "retry_window_bucket ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,31}$'",
        name="ck_sync_runs_retry_window_bucket",
    ),
    ForeignKeyConstraint(
        ["connection_id", "residence_id"],
        ["integrations.connections.id", "integrations.connections.residence_id"],
        ondelete="RESTRICT",
        name="fk_sync_runs_connection_scope",
    ),
    UniqueConstraint(
        "connection_id",
        "idempotency_key",
        name="uq_sync_runs_connection_idempotency",
    ),
    schema="integrations",
)

Index(
    "uq_sync_runs_one_active_per_connection",
    sync_runs.c.connection_id,
    unique=True,
    postgresql_where=text("status IN ('requested', 'running')"),
)
Index(
    "ix_sync_runs_residence_created",
    sync_runs.c.residence_id,
    sync_runs.c.created_at,
)


external_accounts = Table(
    "external_accounts",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("connection_id", UUID(as_uuid=True), nullable=False),
    Column("external_account_id", String(512), nullable=False),
    Column("type", String(16), nullable=False),
    Column("subtype", String(128), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("name", String(512), nullable=True),
    Column("number_mask", String(32), nullable=True),
    Column("status", String(16), nullable=False),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "type IN ('BANK', 'CREDIT', 'INVESTMENT', 'LOAN', 'OTHER')",
        name="ck_external_accounts_type",
    ),
    CheckConstraint(
        "currency ~ '^[A-Z]{3}$'",
        name="ck_external_accounts_currency",
    ),
    CheckConstraint(
        "status IN ('active', 'unavailable', 'disconnected')",
        name="ck_external_accounts_status",
    ),
    CheckConstraint(
        "length(external_account_id) BETWEEN 1 AND 512",
        name="ck_external_accounts_external_id_length",
    ),
    CheckConstraint(
        "length(subtype) BETWEEN 1 AND 128",
        name="ck_external_accounts_subtype_length",
    ),
    CheckConstraint(
        "name IS NULL OR length(name) BETWEEN 1 AND 512",
        name="ck_external_accounts_name_length",
    ),
    CheckConstraint(
        "number_mask IS NULL OR length(number_mask) BETWEEN 1 AND 32",
        name="ck_external_accounts_number_mask_length",
    ),
    CheckConstraint(
        "last_seen_at >= first_seen_at",
        name="ck_external_accounts_seen_order",
    ),
    ForeignKeyConstraint(
        ["connection_id", "residence_id"],
        ["integrations.connections.id", "integrations.connections.residence_id"],
        ondelete="RESTRICT",
        name="fk_external_accounts_connection_scope",
    ),
    UniqueConstraint(
        "connection_id",
        "external_account_id",
        name="uq_external_accounts_connection_external",
    ),
    UniqueConstraint(
        "connection_id",
        "residence_id",
        "external_account_id",
        name="uq_external_accounts_scope",
    ),
    schema="integrations",
)

Index(
    "ix_external_accounts_residence_connection",
    external_accounts.c.residence_id,
    external_accounts.c.connection_id,
)


sync_cursors = Table(
    "sync_cursors",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("residence_id", UUID(as_uuid=True), nullable=False),
    Column("connection_id", UUID(as_uuid=True), nullable=False),
    Column("external_account_id", String(512), nullable=False),
    Column("resource", String(32), nullable=False),
    Column("cursor", String(512), nullable=False),
    Column("source_window", String(256), nullable=False),
    Column("committed_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "resource IN ('transactions')",
        name="ck_sync_cursors_resource",
    ),
    CheckConstraint(
        "length(cursor) BETWEEN 1 AND 512",
        name="ck_sync_cursors_cursor_length",
    ),
    CheckConstraint(
        "length(source_window) BETWEEN 1 AND 256",
        name="ck_sync_cursors_source_window_length",
    ),
    ForeignKeyConstraint(
        ["connection_id", "residence_id", "external_account_id"],
        [
            "integrations.external_accounts.connection_id",
            "integrations.external_accounts.residence_id",
            "integrations.external_accounts.external_account_id",
        ],
        ondelete="RESTRICT",
        name="fk_sync_cursors_external_account_scope",
    ),
    UniqueConstraint(
        "connection_id",
        "external_account_id",
        "resource",
        name="uq_sync_cursors_account_resource",
    ),
    schema="integrations",
)

Index(
    "ix_sync_cursors_residence_connection",
    sync_cursors.c.residence_id,
    sync_cursors.c.connection_id,
)
