# mypy: ignore-errors
"""Create banking provider configuration, connections, capabilities and RLS.

Revision ID: 0003_banking_persistence
Revises: 0002_demo_fixture
Create Date: 2026-07-28
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0003_banking_persistence"
down_revision: str | None = "0002_demo_fixture"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


def _quoted_role() -> str:
    role_name = context.config.get_main_option("app_database_user")
    if not ROLE_PATTERN.fullmatch(role_name):
        raise RuntimeError("invalid app_database_user for migration grants")
    return f'"{role_name}"'


def _create_provider_configurations() -> None:
    op.create_table(
        "provider_configurations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("client_id_envelope", sa.Text(), nullable=True),
        sa.Column("client_secret_envelope", sa.Text(), nullable=True),
        sa.Column("configuration_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "provider ~ '^[a-z][a-z0-9_]{0,62}$'",
            name="ck_provider_configurations_provider",
        ),
        sa.CheckConstraint(
            "state IN ('disabled', 'configured', 'enabled')",
            name="ck_provider_configurations_state",
        ),
        sa.CheckConstraint(
            "configuration_revision > 0",
            name="ck_provider_configurations_revision_positive",
        ),
        sa.CheckConstraint(
            "(client_id_envelope IS NULL) = (client_secret_envelope IS NULL)",
            name="ck_provider_configurations_envelopes_paired",
        ),
        sa.CheckConstraint(
            "state = 'disabled' OR "
            "(client_id_envelope IS NOT NULL AND client_secret_envelope IS NOT NULL)",
            name="ck_provider_configurations_state_credentials",
        ),
        sa.CheckConstraint(
            "state <> 'enabled' OR enabled_at IS NOT NULL",
            name="ck_provider_configurations_enabled_at",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "installation_id",
            "provider",
            name="uq_provider_configurations_installation_provider",
        ),
        sa.UniqueConstraint(
            "id",
            "installation_id",
            "provider",
            name="uq_provider_configurations_scope",
        ),
        schema="integrations",
    )


def _create_connections() -> None:
    op.create_table(
        "connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("residence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column(
            "provider_configuration_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("external_connection_id", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requires_user_action", sa.Boolean(), nullable=False),
        sa.Column(
            "last_successful_sync_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "next_refresh_allowed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("consent_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_reason_code", sa.String(length=128), nullable=True),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provider ~ '^[a-z][a-z0-9_]{0,62}$'",
            name="ck_connections_provider",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'PENDING_USER_ACTION', 'SYNC_REQUESTED', 'SYNCING', 'AVAILABLE', "
            "'PARTIAL', 'REAUTHENTICATION_REQUIRED', 'TEMPORARILY_UNAVAILABLE', "
            "'RATE_LIMITED', 'DISCONNECTED', 'FAILED')",
            name="ck_connections_status",
        ),
        sa.CheckConstraint(
            "provider_reason_code IS NULL OR "
            "provider_reason_code ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'",
            name="ck_connections_provider_reason_code",
        ),
        sa.CheckConstraint(
            "status NOT IN ('PENDING_USER_ACTION', 'REAUTHENTICATION_REQUIRED') "
            "OR requires_user_action",
            name="ck_connections_required_user_action",
        ),
        sa.CheckConstraint(
            "status <> 'DISCONNECTED' OR "
            "(NOT requires_user_action AND disconnected_at IS NOT NULL)",
            name="ck_connections_disconnected_state",
        ),
        sa.ForeignKeyConstraint(
            ["provider_configuration_id", "installation_id", "provider"],
            [
                "integrations.provider_configurations.id",
                "integrations.provider_configurations.installation_id",
                "integrations.provider_configurations.provider",
            ],
            ondelete="RESTRICT",
            name="fk_connections_provider_configuration_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "installation_id",
            "provider",
            "external_connection_id",
            name="uq_connections_external",
        ),
        sa.UniqueConstraint(
            "id",
            "residence_id",
            name="uq_connections_residence_scope",
        ),
        schema="integrations",
    )
    op.create_index(
        "ix_connections_residence_status",
        "connections",
        ["residence_id", "status"],
        unique=False,
        schema="integrations",
    )


def _create_connection_capabilities() -> None:
    op.create_table(
        "connection_capabilities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("residence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("provider_reason_code", sa.String(length=128), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "capability IN ("
            "'identity', 'bank_accounts', 'credit_accounts', 'transactions', "
            "'credit_card_bills', 'investments', 'loans', 'manual_refresh', "
            "'consent_renewal', 'disconnect', 'webhooks')",
            name="ck_connection_capabilities_capability",
        ),
        sa.CheckConstraint(
            "state IN ("
            "'SUPPORTED', 'NOT_AVAILABLE', 'REQUIRES_USER_ACTION', "
            "'NOT_OBSERVED', 'UNKNOWN')",
            name="ck_connection_capabilities_state",
        ),
        sa.CheckConstraint(
            "source IN ('CONTRACT', 'OBSERVATION', 'OPERATION')",
            name="ck_connection_capabilities_source",
        ),
        sa.CheckConstraint(
            "provider_reason_code IS NULL OR "
            "provider_reason_code ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'",
            name="ck_connection_capabilities_provider_reason_code",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "residence_id"],
            [
                "integrations.connections.id",
                "integrations.connections.residence_id",
            ],
            ondelete="CASCADE",
            name="fk_connection_capabilities_connection_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "capability",
            name="uq_connection_capabilities_connection_capability",
        ),
        schema="integrations",
    )
    op.create_index(
        "ix_connection_capabilities_residence_connection",
        "connection_capabilities",
        ["residence_id", "connection_id"],
        unique=False,
        schema="integrations",
    )


def _enable_rls() -> None:
    installation_expression = (
        "installation_id = NULLIF("
        "current_setting('app.current_installation_id', true), '')::uuid"
    )
    residence_expression = (
        "residence_id = NULLIF("
        "current_setting('app.current_residence_id', true), '')::uuid"
    )
    op.execute(
        "ALTER TABLE integrations.provider_configurations ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE integrations.provider_configurations FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY provider_configurations_installation_isolation "
        "ON integrations.provider_configurations "
        f"USING ({installation_expression}) "
        f"WITH CHECK ({installation_expression})"
    )
    op.execute("ALTER TABLE integrations.connections ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE integrations.connections FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY connections_residence_isolation "
        "ON integrations.connections "
        f"USING ({installation_expression} AND {residence_expression}) "
        f"WITH CHECK ({installation_expression} AND {residence_expression})"
    )
    op.execute(
        "ALTER TABLE integrations.connection_capabilities ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE integrations.connection_capabilities FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY connection_capabilities_residence_isolation "
        "ON integrations.connection_capabilities "
        f"USING ({residence_expression}) "
        f"WITH CHECK ({residence_expression})"
    )


def upgrade() -> None:
    role = _quoted_role()
    op.execute("CREATE SCHEMA IF NOT EXISTS integrations")
    _create_provider_configurations()
    _create_connections()
    _create_connection_capabilities()
    _enable_rls()
    op.execute(f"GRANT USAGE ON SCHEMA integrations TO {role}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE "
        f"ON ALL TABLES IN SCHEMA integrations TO {role}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA integrations "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}"
    )


def downgrade() -> None:
    role = _quoted_role()
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA integrations "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {role}"
    )
    op.execute(
        f"REVOKE SELECT, INSERT, UPDATE, DELETE "
        f"ON ALL TABLES IN SCHEMA integrations FROM {role}"
    )
    op.execute(f"REVOKE USAGE ON SCHEMA integrations FROM {role}")
    op.drop_index(
        "ix_connection_capabilities_residence_connection",
        table_name="connection_capabilities",
        schema="integrations",
    )
    op.drop_table("connection_capabilities", schema="integrations")
    op.drop_index(
        "ix_connections_residence_status",
        table_name="connections",
        schema="integrations",
    )
    op.drop_table("connections", schema="integrations")
    op.drop_table("provider_configurations", schema="integrations")
    op.execute("DROP SCHEMA IF EXISTS integrations")
