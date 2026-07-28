from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from meufinanceiro_banking import (
    Capability,
    CapabilitySource,
    CapabilityState,
    ConnectionStatus,
)
from meufinanceiro_persistence import (
    ProviderConfigurationRecord,
    StoredCapability,
    StoredCapabilitySource,
    StoredCapabilityState,
    StoredConnectionStatus,
)
from meufinanceiro_persistence.schema import (
    connection_capabilities,
    connections,
    provider_configurations,
)

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "packages"
    / "persistence"
    / "src"
    / "meufinanceiro_persistence"
    / "migrations"
    / "versions"
    / "0003_banking_persistence.py"
)


def _values(enum_type: type) -> set[str]:
    return {str(item.value) for item in enum_type}


def test_persisted_enums_match_neutral_banking_contract() -> None:
    assert _values(StoredConnectionStatus) == _values(ConnectionStatus)
    assert _values(StoredCapability) == _values(Capability)
    assert _values(StoredCapabilityState) == _values(CapabilityState)
    assert _values(StoredCapabilitySource) == _values(CapabilitySource)


def test_public_configuration_record_never_contains_envelopes() -> None:
    names = {field.name for field in fields(ProviderConfigurationRecord)}

    assert "client_id_envelope" not in names
    assert "client_secret_envelope" not in names


def test_schema_has_no_ephemeral_or_banking_auth_secret_columns() -> None:
    column_names = {
        column.name.lower()
        for table in (
            provider_configurations,
            connections,
            connection_capabilities,
        )
        for column in table.columns
    }

    forbidden = {
        "api_key",
        "connect_token",
        "password",
        "mfa",
        "raw_payload",
        "headers",
        "cookies",
    }
    assert column_names.isdisjoint(forbidden)


def test_migration_forces_fail_closed_rls_contexts() -> None:
    content = MIGRATION.read_text(encoding="utf-8")

    assert content.count("FORCE ROW LEVEL SECURITY") == 3
    assert "app.current_installation_id" in content
    assert "app.current_residence_id" in content
    assert "current_setting('app.current_installation_id', true)" in content
    assert "current_setting('app.current_residence_id', true)" in content
    assert "NULLIF(" in content
    assert "BYPASSRLS" not in content


def test_migration_contains_only_minimum_banking_tables() -> None:
    content = MIGRATION.read_text(encoding="utf-8")

    for required in (
        "provider_configurations",
        "connections",
        "connection_capabilities",
    ):
        assert required in content

    for deferred in (
        "external_accounts",
        "external_observations",
        "sync_runs",
        "sync_cursors",
        "audit_events",
    ):
        assert f'create_table(\n        "{deferred}"' not in content
