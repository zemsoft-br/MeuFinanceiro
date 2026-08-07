from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PARSER_SOURCE = (
    ROOT
    / "packages/banking-pluggy/src/meufinanceiro_banking_pluggy/connected_item.py"
).read_text(encoding="utf-8")
REGISTRATION_SOURCE = (
    ROOT
    / "packages/banking-pluggy-execution/src/"
    "meufinanceiro_banking_pluggy_execution/registration.py"
).read_text(encoding="utf-8")
ROUTE_SOURCE = (ROOT / "apps/api/app/api/routes/banking_connections.py").read_text(
    encoding="utf-8"
)
MAIN_SOURCE = (ROOT / "apps/api/app/main.py").read_text(encoding="utf-8")
CONFIG_SOURCE = (ROOT / "apps/api/app/core/config.py").read_text(encoding="utf-8")
PERSISTENCE_SOURCE = "\n".join(
    path.read_text(encoding="utf-8")
    for path in sorted(
        (ROOT / "packages/persistence/src/meufinanceiro_persistence").rglob("*.py")
    )
)


def test_item_ownership_is_verified_before_connection_persistence() -> None:
    assert 'payload.get("clientUserId")' in PARSER_SOURCE
    assert "client_user_id != normalized_expected_client_user_id" in PARSER_SOURCE
    assert "ITEM_OWNERSHIP_MISMATCH" in PARSER_SOURCE
    assert 'expected_client_user_id = f"residence:{residence_id}"' in REGISTRATION_SOURCE
    assert REGISTRATION_SOURCE.index("parse_connected_item(") < REGISTRATION_SOURCE.index(
        "self._store.register_connection("
    )


def test_registration_request_does_not_accept_authorization_scope() -> None:
    assert 'alias="itemId"' in ROUTE_SOURCE
    assert 'ConfigDict(extra="forbid")' in ROUTE_SOURCE
    assert "request.query_params" in ROUTE_SOURCE
    for forbidden in (
        'alias="residenceId"',
        'alias="installationId"',
        'alias="clientUserId"',
        'alias="status"',
        'alias="capabilities"',
    ):
        assert forbidden not in ROUTE_SOURCE


def test_public_response_contains_local_connection_state_only() -> None:
    assert 'serialization_alias="connectionId"' in ROUTE_SOURCE
    assert 'serialization_alias="requiresUserAction"' in ROUTE_SOURCE
    response_source = ROUTE_SOURCE.split("class RegisteredPluggyConnectionResponse", 1)[1]
    response_source = response_source.split("async def _require_registration_request", 1)[0]
    assert "item_id" not in response_source
    assert "external_connection_id" not in response_source
    assert "client_user_id" not in response_source


def test_registration_uses_ephemeral_credentials_and_provider_verification() -> None:
    assert "use_enabled_credentials" in REGISTRATION_SOURCE
    assert 'provider="pluggy"' in REGISTRATION_SOURCE
    assert "transport.get_item(normalized_item_id)" in REGISTRATION_SOURCE
    assert "transport.close()" in REGISTRATION_SOURCE
    assert "register_connection(" in REGISTRATION_SOURCE
    assert "replace_capabilities(" in REGISTRATION_SOURCE


def test_registration_does_not_create_provider_item_or_store_provider_payload() -> None:
    assert '"POST"' not in REGISTRATION_SOURCE
    assert "create_item" not in REGISTRATION_SOURCE
    lowered_persistence = PERSISTENCE_SOURCE.casefold()
    assert "client_user_id" not in lowered_persistence
    assert "clientuserid" not in lowered_persistence
    assert "provider_payload" not in lowered_persistence
    assert "raw_payload" not in lowered_persistence


def test_registration_runtime_remains_flag_gated_and_startup_passive() -> None:
    assert "PluggyConnectionRegistrationService" in MAIN_SOURCE
    assert "resolved_settings.app_banking_enabled" in MAIN_SOURCE
    assert "resolved_settings.app_banking_pluggy_enabled" in MAIN_SOURCE
    assert "PluggyGatewayHttpTransport(" not in MAIN_SOURCE
    assert "use_enabled_credentials" not in MAIN_SOURCE
    assert "app_banking_enabled: bool = False" in CONFIG_SOURCE
    assert "app_banking_pluggy_enabled: bool = False" in CONFIG_SOURCE
