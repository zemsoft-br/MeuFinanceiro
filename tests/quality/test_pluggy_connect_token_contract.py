from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRANSPORT_SOURCE = (
    ROOT
    / "packages/banking-pluggy/src/meufinanceiro_banking_pluggy/connect_token.py"
).read_text(encoding="utf-8")
EXECUTION_SOURCE = (
    ROOT
    / "packages/banking-pluggy-execution/src/"
    "meufinanceiro_banking_pluggy_execution/connect_token.py"
).read_text(encoding="utf-8")
ROUTE_SOURCE = (ROOT / "apps/api/app/api/routes/banking_connect.py").read_text(
    encoding="utf-8"
)
AUTH_SOURCE = (ROOT / "apps/api/app/api/auth.py").read_text(encoding="utf-8")
MAIN_SOURCE = (ROOT / "apps/api/app/main.py").read_text(encoding="utf-8")
CONFIG_SOURCE = (ROOT / "apps/api/app/core/config.py").read_text(encoding="utf-8")
PERSISTENCE_SOURCE = "\n".join(
    path.read_text(encoding="utf-8")
    for path in sorted(
        (ROOT / "packages/persistence/src/meufinanceiro_persistence").rglob("*.py")
    )
)


def test_connect_token_payload_is_server_scoped_and_minimal() -> None:
    assert '"clientUserId": normalized_client_user_id' in TRANSPORT_SOURCE
    assert '"avoidDuplicates": True' in TRANSPORT_SOURCE
    for forbidden in (
        '"itemId"',
        '"webhookUrl"',
        '"oauthRedirectUri"',
        '"connectorId"',
        '"products"',
    ):
        assert forbidden not in TRANSPORT_SOURCE


def test_connect_token_transport_does_not_enable_item_creation() -> None:
    assert 'path == "connect_token"' in TRANSPORT_SOURCE
    assert '"POST",\n                "connect_token"' in TRANSPORT_SOURCE
    assert 'path == "items"' not in TRANSPORT_SOURCE
    assert '"POST",\n                "items"' not in TRANSPORT_SOURCE


def test_connect_token_scope_is_derived_from_authenticated_residence() -> None:
    assert 'client_user_id = f"residence:{residence_id}"' in EXECUTION_SOURCE
    assert 'provider="pluggy"' in EXECUTION_SOURCE
    assert "use_enabled_credentials" in EXECUTION_SOURCE
    assert "installation_id=authenticated.principal.installation_id" in ROUTE_SOURCE
    assert "residence_id=residence_id" in ROUTE_SOURCE
    assert "require_installation_admin_primary_residence" in ROUTE_SOURCE
    assert "primary_residence_id" in ROUTE_SOURCE


def test_connect_token_route_accepts_no_client_controlled_parameters() -> None:
    assert "request.query_params" in ROUTE_SOURCE
    assert "query parameters are not allowed" in ROUTE_SOURCE
    assert "await request.body()" in ROUTE_SOURCE
    assert "request body is not allowed" in ROUTE_SOURCE
    for forbidden in (
        "client_user_id:",
        "residence_id:",
        "installation_id:",
        "item_id:",
        "webhook_url:",
        "oauth_redirect_uri:",
    ):
        assert forbidden not in ROUTE_SOURCE


def test_connect_token_is_no_store_and_composed_only_behind_both_flags() -> None:
    assert '"/api/v1/banking/"' in AUTH_SOURCE
    assert "resolved_settings.app_banking_enabled" in MAIN_SOURCE
    assert "resolved_settings.app_banking_pluggy_enabled" in MAIN_SOURCE
    assert MAIN_SOURCE.count("PluggyConnectTokenService(banking_store)") == 1
    assert 'include_router(banking_connect_router, prefix="/api/v1")' in MAIN_SOURCE
    assert "app_banking_enabled: bool = False" in CONFIG_SOURCE
    assert "app_banking_pluggy_enabled: bool = False" in CONFIG_SOURCE


def test_connect_token_and_api_key_have_no_persistence_fields() -> None:
    lowered = PERSISTENCE_SOURCE.casefold()
    assert "access_token" not in lowered
    assert "connect_token" not in lowered
    assert "api_key" not in lowered
