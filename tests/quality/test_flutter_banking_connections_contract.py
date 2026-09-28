from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps/app"
FEATURE = APP / "lib/features/banking/connections"
API_SOURCE = (FEATURE / "banking_connections_api.dart").read_text(encoding="utf-8")
CONTROLLER_SOURCE = (FEATURE / "banking_connections_controller.dart").read_text(
    encoding="utf-8"
)
SCREEN_SOURCE = (FEATURE / "banking_connections_screen.dart").read_text(
    encoding="utf-8"
)
ROUTES_SOURCE = (APP / "lib/routing/app_routes.dart").read_text(encoding="utf-8")
ROUTER_SOURCE = (APP / "lib/routing/app_router.dart").read_text(encoding="utf-8")
SW_SOURCE = (APP / "web/sw.js").read_text(encoding="utf-8")


def test_overview_uses_only_local_authenticated_connections_endpoint() -> None:
    assert "client.get('banking/connections')" in API_SOURCE
    assert "client.post(" not in API_SOURCE
    assert "client.delete(" not in API_SOURCE
    assert "queryParameters" not in API_SOURCE
    assert "residenceId" not in API_SOURCE
    assert "installationId" not in API_SOURCE


def test_provider_external_identifiers_never_enter_overview_contract() -> None:
    production = "\n".join((API_SOURCE, CONTROLLER_SOURCE, SCREEN_SOURCE))
    for forbidden in (
        "external_connection_id",
        "externalConnectionId",
        "itemId",
        "clientUserId",
        "providerReasonCode",
        "provider_reason_code",
        "accessToken",
        "connectToken",
        "client_secret",
        "clientSecret",
        "apiKey",
    ):
        assert forbidden not in production


def test_overview_has_no_storage_polling_or_background_sync() -> None:
    production = "\n".join((API_SOURCE, CONTROLLER_SOURCE, SCREEN_SOURCE))
    for forbidden in (
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "SharedPreferences",
        "sqflite",
        "Timer.periodic",
        "Stream.periodic",
        "backgroundFetch",
    ):
        assert forbidden not in production

    assert "Future<void> refresh()" in CONTROLLER_SOURCE
    assert "if (_inFlight || state.isBusy)" in CONTROLLER_SOURCE


def test_reauthentication_action_trusts_backend_availability_and_local_id() -> None:
    assert "if (connection.reauthenticationAvailable)" in SCREEN_SOURCE
    assert "AppRoutes.pluggyReauthenticationLocation(connectionId)" in SCREEN_SOURCE
    assert "onReauthenticate(connection.connectionId)" in SCREEN_SOURCE
    assert "connection.status ==" not in SCREEN_SOURCE
    assert "connection.provider ==" not in SCREEN_SOURCE


def test_integrations_route_is_protected_namespace_and_selects_children() -> None:
    assert "static const integrationsPath = '/app/integracoes';" in ROUTES_SOURCE
    assert "path.startsWith('${destination.path}/')" in ROUTES_SOURCE
    assert "AppRouteId.integrations" in ROUTES_SOURCE
    assert "path: AppRoutes.integrationsPath" in ROUTER_SOURCE
    assert "BankingConnectionsScreen" in ROUTER_SOURCE


def test_service_worker_still_excludes_api_and_cross_origin_requests() -> None:
    assert "url.origin !== self.location.origin" in SW_SOURCE
    assert "url.pathname === '/api'" in SW_SOURCE
    assert "url.pathname.startsWith('/api/')" in SW_SOURCE
