from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUTH_ROOT = ROOT / "apps/app/lib/core/auth"
AUTH_SOURCE = "\n".join(
    path.read_text(encoding="utf-8") for path in sorted(AUTH_ROOT.glob("*.dart"))
)
LOGIN_SOURCE = (
    ROOT / "apps/app/lib/features/auth/login_screen.dart"
).read_text(encoding="utf-8")
ROUTER_SOURCE = (ROOT / "apps/app/lib/routing/app_router.dart").read_text(
    encoding="utf-8"
)
GUARD_SOURCE = (ROOT / "apps/app/lib/routing/auth_route_guard.dart").read_text(
    encoding="utf-8"
)
SERVICE_WORKER_SOURCE = (ROOT / "apps/app/web/sw.js").read_text(encoding="utf-8")


def test_bearer_is_memory_only_and_never_logged() -> None:
    for forbidden in (
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "IndexedDB",
        "SharedPreferences",
        "sqflite",
        "sqlite",
        "debugPrint(",
        "print(",
    ):
        assert forbidden not in AUTH_SOURCE
        assert forbidden not in LOGIN_SOURCE

    assert "class SessionTokenVault" in AUTH_SOURCE
    assert "SessionTokenVault(<redacted>)" in AUTH_SOURCE
    assert "Authorization': 'Bearer $token'" in AUTH_SOURCE


def test_login_request_cannot_supply_authorization_scope() -> None:
    service = (
        ROOT / "apps/app/lib/core/auth/operator_session_service.dart"
    ).read_text(encoding="utf-8")
    login_body = service.split("jsonEncode(", 1)[1].split("),", 1)[0]

    assert "'login': normalizedLogin" in login_body
    assert "'password': password" in login_body
    for forbidden in (
        "installation_id",
        "operator_id",
        "residence_id",
        "primary_residence_id",
    ):
        assert forbidden not in login_body


def test_protected_routes_redirect_through_canonical_login() -> None:
    assert "path: '/login'" in GUARD_SOURCE
    assert "redirect" in GUARD_SOURCE
    assert "uri.hasScheme" in GUARD_SOURCE
    assert "uri.hasAuthority" in GUARD_SOURCE
    assert "path: AppRoutes.loginPath" in ROUTER_SOURCE


def test_pwa_still_excludes_api_from_shell_cache() -> None:
    assert "'/api'" in SERVICE_WORKER_SOURCE
    assert "'/api/'" in SERVICE_WORKER_SOURCE
