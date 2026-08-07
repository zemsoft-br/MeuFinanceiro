from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from meufinanceiro_banking_pluggy_execution import (
    IssuedPluggyConnectToken,
    PluggyConnectTokenError,
    PluggyConnectTokenErrorCode,
)
from meufinanceiro_persistence import OperatorRole, OperatorSessionPrincipal
from meufinanceiro_security.keyring import initialize_keyring_file

from app.core.config import Settings
from app.main import create_app
from app.services.operator_auth import InvalidOperatorSessionError

TOKEN = "C" * 43
CONNECT_TOKEN = "ephemeral-connect-token-secret"
INSTALLATION_ID = UUID("10000000-0000-4000-8000-000000000001")
RESIDENCE_ID = UUID("20000000-0000-4000-8000-000000000002")
OPERATOR_ID = UUID("30000000-0000-4000-8000-000000000003")
NOW = datetime(2026, 8, 7, tzinfo=UTC)
PATH = "/api/v1/banking/pluggy/connect-token"


def principal(
    *,
    admin: bool = True,
    residence_id: UUID | None = RESIDENCE_ID,
) -> OperatorSessionPrincipal:
    return OperatorSessionPrincipal(
        session_id=uuid4(),
        installation_id=INSTALLATION_ID,
        operator_id=OPERATOR_ID,
        login_name="admin",
        role=(
            OperatorRole.INSTALLATION_ADMIN
            if admin
            else cast(OperatorRole, "residence_member")
        ),
        expires_at=NOW,
        primary_residence_id=residence_id,
    )


class FakeAuthentication:
    def __init__(self) -> None:
        self.principal = principal()

    def resolve(self, token: str) -> OperatorSessionPrincipal:
        if token != TOKEN:
            raise InvalidOperatorSessionError("operator session is invalid")
        return self.principal


class FakeConnectTokenService:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID]] = []
        self.error: PluggyConnectTokenError | None = None

    def issue(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
    ) -> IssuedPluggyConnectToken:
        self.calls.append((installation_id, residence_id))
        if self.error is not None:
            raise self.error
        return IssuedPluggyConnectToken(CONNECT_TOKEN)


@pytest.fixture
def client(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, FakeAuthentication, FakeConnectTokenService]]:
    keyring = tmp_path / "keyring.json"
    initialize_keyring_file(keyring)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=keyring,
    )
    authentication = FakeAuthentication()
    service = FakeConnectTokenService()
    with TestClient(create_app(settings)) as test_client:
        test_client.app.state.operator_authentication = authentication
        test_client.app.state.banking_pluggy_connect_token = service
        yield test_client, authentication, service


def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def assert_no_store(response: httpx.Response) -> None:
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_connect_token_derives_installation_and_residence_from_session(
    client: tuple[TestClient, FakeAuthentication, FakeConnectTokenService],
) -> None:
    test_client, _, service = client

    response = test_client.post(PATH, headers=headers())

    assert response.status_code == 200
    assert response.json() == {"accessToken": CONNECT_TOKEN}
    assert service.calls == [(INSTALLATION_ID, RESIDENCE_ID)]
    assert str(INSTALLATION_ID) not in response.text
    assert str(RESIDENCE_ID) not in response.text
    assert_no_store(response)


def test_connect_token_requires_active_admin_session(
    client: tuple[TestClient, FakeAuthentication, FakeConnectTokenService],
) -> None:
    test_client, authentication, service = client

    unauthenticated = test_client.post(PATH)
    authentication.principal = principal(admin=False)
    forbidden = test_client.post(PATH, headers=headers())

    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["www-authenticate"] == "Bearer"
    assert forbidden.status_code == 403
    assert service.calls == []
    assert_no_store(unauthenticated)
    assert_no_store(forbidden)


def test_connect_token_requires_primary_residence(
    client: tuple[TestClient, FakeAuthentication, FakeConnectTokenService],
) -> None:
    test_client, authentication, service = client
    authentication.principal = principal(residence_id=None)

    response = test_client.post(PATH, headers=headers())

    assert response.status_code == 409
    assert response.json() == {"detail": "primary residence is required"}
    assert service.calls == []
    assert_no_store(response)


def test_connect_token_rejects_any_request_body(
    client: tuple[TestClient, FakeAuthentication, FakeConnectTokenService],
) -> None:
    test_client, _, service = client

    response = test_client.post(
        PATH,
        headers=headers(),
        json={
            "residence_id": str(uuid4()),
            "clientUserId": "attacker-controlled",
            "itemId": "provider-item",
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "request body is not allowed"}
    assert service.calls == []
    assert_no_store(response)


def test_connect_token_is_unavailable_when_runtime_service_is_not_composed(
    client: tuple[TestClient, FakeAuthentication, FakeConnectTokenService],
) -> None:
    test_client, _, service = client
    test_client.app.state.banking_pluggy_connect_token = None

    response = test_client.post(PATH, headers=headers())

    assert response.status_code == 404
    assert response.json() == {"detail": "banking provider is unavailable"}
    assert service.calls == []
    assert_no_store(response)


@pytest.mark.parametrize(
    ("code", "status_code"),
    [
        (PluggyConnectTokenErrorCode.CONFIGURATION_REQUIRED, 409),
        (PluggyConnectTokenErrorCode.PROVIDER_NOT_ENABLED, 409),
        (PluggyConnectTokenErrorCode.TEMPORARILY_UNAVAILABLE, 503),
        (PluggyConnectTokenErrorCode.INVALID_PROVIDER_RESPONSE, 502),
        (PluggyConnectTokenErrorCode.PROVIDER_REJECTED, 502),
        (PluggyConnectTokenErrorCode.INTERNAL, 503),
    ],
)
def test_connect_token_errors_have_stable_http_mapping(
    client: tuple[TestClient, FakeAuthentication, FakeConnectTokenService],
    code: PluggyConnectTokenErrorCode,
    status_code: int,
) -> None:
    test_client, _, service = client
    service.error = PluggyConnectTokenError(code)

    response = test_client.post(PATH, headers=headers())

    assert response.status_code == status_code
    assert CONNECT_TOKEN not in response.text
    assert str(INSTALLATION_ID) not in response.text
    assert str(RESIDENCE_ID) not in response.text
    assert_no_store(response)


def test_connect_token_openapi_has_no_client_controlled_scope_or_options(
    client: tuple[TestClient, FakeAuthentication, FakeConnectTokenService],
) -> None:
    test_client, _, _ = client
    schema = test_client.get("/api/v1/openapi.json").json()
    operation = schema["paths"][PATH]["post"]

    assert "requestBody" not in operation
    serialized = str(operation)
    for forbidden in (
        "installation_id",
        "residence_id",
        "clientUserId",
        "itemId",
        "webhookUrl",
        "oauthRedirectUri",
    ):
        assert forbidden not in serialized
