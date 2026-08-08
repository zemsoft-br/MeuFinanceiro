from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRANSPORT_SOURCE = (
    ROOT
    / "packages/banking-pluggy/src/meufinanceiro_banking_pluggy/connect_token.py"
).read_text(encoding="utf-8")
SERVICE_SOURCE = (
    ROOT
    / "packages/banking-pluggy-execution/src/"
    "meufinanceiro_banking_pluggy_execution/reauthentication.py"
).read_text(encoding="utf-8")
ROUTE_SOURCE = (
    ROOT / "apps/api/app/api/routes/banking_reauthentication.py"
).read_text(encoding="utf-8")
MAIN_SOURCE = (ROOT / "apps/api/app/main.py").read_text(encoding="utf-8")
CONFIG_SOURCE = (ROOT / "apps/api/app/core/config.py").read_text(encoding="utf-8")


def test_local_connection_is_resolved_before_credentials_or_provider_io() -> None:
    assert SERVICE_SOURCE.index("self._store.get_connection(") < SERVICE_SOURCE.index(
        "self._store.use_enabled_credentials("
    )
    assert SERVICE_SOURCE.index("parse_connected_item(") < SERVICE_SOURCE.index(
        "transport.create_update_connect_token("
    )
    assert 'expected_client_user_id = f"residence:{residence_id}"' in SERVICE_SOURCE
    assert "connection.external_connection_id" in SERVICE_SOURCE


def test_update_connect_token_is_bound_only_to_verified_item() -> None:
    method = TRANSPORT_SOURCE.split("def create_update_connect_token", 1)[1].split(
        "def _create_connect_token", 1
    )[0]
    assert '{"itemId": normalized_item_id}' in method
    for forbidden in (
        "clientUserId",
        "avoidDuplicates",
        "webhookUrl",
        "oauthRedirectUri",
        "forceAskForCredentials",
    ):
        assert forbidden not in method
    assert '"PATCH"' not in TRANSPORT_SOURCE


def test_reauthentication_http_input_contains_only_local_connection_path_id() -> None:
    assert '"/connections/{connection_id}/reauthentication-token"' in ROUTE_SOURCE
    assert "request.query_params" in ROUTE_SOURCE
    assert "request.stream()" in ROUTE_SOURCE
    assert "class PluggyReauthenticationTokenResponse" in ROUTE_SOURCE
    assert "class PluggyReauthenticationTokenRequest" not in ROUTE_SOURCE
    assert "payload:" not in ROUTE_SOURCE
    for forbidden in (
        'alias="residenceId"',
        'alias="installationId"',
        'alias="clientUserId"',
        'alias="provider"',
    ):
        assert forbidden not in ROUTE_SOURCE


def test_reauthentication_response_is_ephemeral_and_redacted() -> None:
    assert 'serialization_alias="accessToken"' in ROUTE_SOURCE
    assert 'serialization_alias="itemId"' in ROUTE_SOURCE
    assert "IssuedPluggyReauthenticationToken(<redacted>)" in SERVICE_SOURCE
    assert "Cache-Control" not in SERVICE_SOURCE
    assert "Pragma" not in SERVICE_SOURCE


def test_reauthentication_runtime_remains_flag_gated_and_startup_passive() -> None:
    assert "PluggyReauthenticationTokenService" in MAIN_SOURCE
    assert "resolved_settings.app_banking_enabled" in MAIN_SOURCE
    assert "resolved_settings.app_banking_pluggy_enabled" in MAIN_SOURCE
    assert "PluggyConnectTokenHttpTransport(" not in MAIN_SOURCE
    assert "use_enabled_credentials" not in MAIN_SOURCE
    assert "app_banking_enabled: bool = False" in CONFIG_SOURCE
    assert "app_banking_pluggy_enabled: bool = False" in CONFIG_SOURCE
