from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from meufinanceiro_persistence import OperatorRole, OperatorSessionPrincipal
from meufinanceiro_security.keyring import initialize_keyring_file

from app.core.config import Settings
from app.main import create_app
from app.services.operator_auth import (
    InvalidOperatorCredentialsError,
    InvalidOperatorSessionError,
    IssuedOperatorSession,
)

TOKEN = "Z" * 43
PRINCIPAL = OperatorSessionPrincipal(
    session_id=uuid4(),
    installation_id=uuid4(),
    operator_id=uuid4(),
    login_name="admin",
    role=OperatorRole.INSTALLATION_ADMIN,
    expires_at=datetime(2026, 8, 6, tzinfo=UTC),
)


class FakeAuthenticationService:
    def __init__(self) -> None:
        self.login_error: Exception | None = None
        self.resolve_error: Exception | None = None
        self.logout_calls: list[str] = []

    def login(self, *, login_name: str, password: str) -> IssuedOperatorSession:
        del login_name, password
        if self.login_error is not None:
            raise self.login_error
        return IssuedOperatorSession(token=TOKEN, principal=PRINCIPAL)

    def resolve(self, token: str) -> OperatorSessionPrincipal:
        if self.resolve_error is not None:
            raise self.resolve_error
        if token != TOKEN:
            raise InvalidOperatorSessionError("operator session is invalid")
        return PRINCIPAL

    def logout(self, token: str) -> None:
        self.logout_calls.append(token)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[tuple[TestClient, FakeAuthenticationService]]:
    keyring = tmp_path / "keyring.json"
    initialize_keyring_file(keyring)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=keyring,
    )
    authentication = FakeAuthenticationService()
    with TestClient(create_app(settings)) as test_client:
        test_client.app.state.operator_authentication = authentication
        yield test_client, authentication


def test_login_returns_token_once_and_no_store_headers(
    client: tuple[TestClient, FakeAuthenticationService],
) -> None:
    test_client, _ = client
    response = test_client.post(
        "/api/v1/auth/session",
        json={"login": "admin", "password": "test-password"},
    )

    assert response.status_code == 200
    assert response.json()["access_token"] == TOKEN
    assert response.json()["operator"]["role"] == "installation_admin"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_login_failure_is_generic_and_no_store(
    client: tuple[TestClient, FakeAuthenticationService],
) -> None:
    test_client, authentication = client
    authentication.login_error = InvalidOperatorCredentialsError(
        "operator credentials are invalid"
    )

    response = test_client.post(
        "/api/v1/auth/session",
        json={"login": "missing", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "operator credentials are invalid"}
    assert response.headers["cache-control"] == "no-store"
    assert TOKEN not in response.text


def test_me_and_logout_require_active_bearer_session(
    client: tuple[TestClient, FakeAuthenticationService],
) -> None:
    test_client, authentication = client
    headers = {"Authorization": f"Bearer {TOKEN}"}

    me = test_client.get("/api/v1/auth/session", headers=headers)
    logout = test_client.delete("/api/v1/auth/session", headers=headers)

    assert me.status_code == 200
    assert me.json()["login"] == "admin"
    assert logout.status_code == 204
    assert authentication.logout_calls == [TOKEN]
    assert TOKEN not in me.text
    assert TOKEN not in logout.text


def test_missing_or_invalid_bearer_is_unauthorized(
    client: tuple[TestClient, FakeAuthenticationService],
) -> None:
    test_client, _ = client
    for headers in (
        {},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer bad"},
    ):
        response = test_client.get("/api/v1/auth/session", headers=headers)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.headers["cache-control"] == "no-store"


def test_health_and_demo_remain_public(
    client: tuple[TestClient, FakeAuthenticationService],
) -> None:
    test_client, _ = client
    assert test_client.get("/api/v1/health/live").status_code == 200
    assert test_client.get("/api/v1/demo/status").status_code == 200
