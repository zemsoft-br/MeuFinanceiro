from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "packages/persistence/src/meufinanceiro_persistence/migrations/versions/0004_operator_authentication.py"
).read_text(encoding="utf-8")
IDENTITY_SCHEMA = (
    ROOT
    / "packages/persistence/src/meufinanceiro_persistence/identity_schema.py"
).read_text(encoding="utf-8")
AUTH_SERVICE = (ROOT / "apps/api/app/services/operator_auth.py").read_text(
    encoding="utf-8"
)
AUTH_ROUTES = (ROOT / "apps/api/app/api/routes/auth.py").read_text(
    encoding="utf-8"
)
CLI = (ROOT / "apps/api/app/operator_cli.py").read_text(encoding="utf-8")
MAIN = (ROOT / "apps/api/app/main.py").read_text(encoding="utf-8")


def test_authentication_uses_opaque_hashed_sessions_without_jwt() -> None:
    combined = "\n".join(
        (MIGRATION, IDENTITY_SCHEMA, AUTH_SERVICE, AUTH_ROUTES, MAIN)
    ).casefold()
    assert "token_hash" in combined
    assert "sha256" in AUTH_SERVICE.casefold()
    assert "token_urlsafe" in AUTH_SERVICE
    for forbidden in (
        "pyjwt",
        "python-jose",
        "jose.jwt",
        "oauth2passwordbearer",
        "firebase",
        "auth0",
    ):
        assert forbidden not in combined


def test_database_schema_does_not_persist_raw_password_or_bearer_token() -> None:
    lowered = "\n".join((MIGRATION, IDENTITY_SCHEMA)).casefold()
    assert "password_hash" in lowered
    assert "token_hash" in lowered
    for forbidden in (
        'column("password",',
        'column("access_token",',
        'column("refresh_token",',
        'column("bearer_token",',
        'column("authorization",',
    ):
        assert forbidden not in lowered


def test_bootstrap_password_is_interactive_only() -> None:
    assert "getpass.getpass" in CLI
    assert "sys.stdin.isatty()" in CLI
    assert 'add_argument("--password"' not in CLI
    assert "os.environ" not in CLI


def test_only_session_endpoints_are_added_and_banking_remains_unexposed() -> None:
    assert '@router.post("/session"' in AUTH_ROUTES
    assert '@router.get("/session"' in AUTH_ROUTES
    assert '@router.delete("/session"' in AUTH_ROUTES
    assert "/banking" not in AUTH_ROUTES
    assert "banking_administration" not in AUTH_ROUTES
    assert "banking_pluggy_execution" not in AUTH_ROUTES


def test_authentication_routes_are_no_store_and_health_demo_stay_public() -> None:
    assert "AuthenticationNoStoreMiddleware" in MAIN
    assert 'include_router(auth_router, prefix="/api/v1")' in MAIN
    assert 'include_router(health_router, prefix="/api/v1")' in MAIN
    assert 'include_router(demo_router, prefix="/api/v1")' in MAIN
