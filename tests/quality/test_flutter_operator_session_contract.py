from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUTH_ROOT = ROOT / "apps/app/lib/core/auth"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


AUTH_SOURCE = "\n".join(_read(path) for path in sorted(AUTH_ROOT.glob("*.dart")))
LOGIN_SOURCE = _read(ROOT / "apps/app/lib/features/auth/login_screen.dart")
ROUTER_SOURCE = _read(ROOT / "apps/app/lib/routing/app_router.dart")
GUARD_SOURCE = _read(ROOT / "apps/app/lib/routing/auth_route_guard.dart")
SERVICE_WORKER_SOURCE = _read(ROOT / "apps/app/web/sw.js")


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
    assert "access_token" not in LOGIN_SOURCE


def test_login_request_cannot_supply_authorization_scope() -> None:
    service = _read(ROOT / "apps/app/lib/core/auth/operator_session_service.dart")
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
    assert "path == '/app'" in GUARD_SOURCE
    assert "path.startsWith('/app/')" in GUARD_SOURCE
    assert "path: '/login'" in GUARD_SOURCE
    assert "uri.hasScheme" in GUARD_SOURCE
    assert "uri.hasAuthority" in GUARD_SOURCE
    assert "path: AppRoutes.loginPath" in ROUTER_SOURCE
    assert "refreshListenable:" in ROUTER_SOURCE
    assert "operatorSessionControllerProvider" in ROUTER_SOURCE


def test_pwa_still_excludes_api_from_shell_cache() -> None:
    assert "'/api'" in SERVICE_WORKER_SOURCE
    assert "'/api/'" in SERVICE_WORKER_SOURCE
