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
    IssuedPluggyReauthenticationToken,
    PluggyReauthenticationError,
    PluggyReauthenticationErrorCode,
)
from meufinanceiro_persistence import OperatorRole, OperatorSessionPrincipal
from meufinanceiro_security.keyring import initialize_keyring_file

from app.core.config import Settings
from app.main import create_app
from app.services.operator_auth import InvalidOperatorSessionError

TOKEN = "R" * 43
CONNECT_TOKEN = "C" * 43
ITEM_ID = "synthetic-existing-item"
INSTALLATION_ID = UUID("10000000-0000-4000-8000-000000000001")
RESIDENCE_ID = UUID("20000000-0000-4000-8000-000000000002")
OPERATOR_ID = UUID("30000000-0000-4000-8000-000000000003")
CONNECTION_ID = UUID("40000000-0000-4000-8000-000000000004")
NOW = datetime(2026, 8, 8, tzinfo=UTC)
PATH = f"/api/v1/banking/pluggy/connections/{CONNECTION_ID}/reauthentication-token"


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


class FakeReauthenticationService:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID, UUID]] = []
        self.error: PluggyReauthenticationError | None = None

    def issue(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
    ) -> IssuedPluggyReauthenticationToken:
        self.calls.append((installation_id, residence_id, connection_id))
        if self.error is not None:
            raise self.error
        return IssuedPluggyReauthenticationToken(
            access_token=CONNECT_TOKEN,
            item_id=ITEM_ID,
        )


@pytest.fixture
def client(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, FakeAuthentication, FakeReauthenticationService]]:
    keyring = tmp_path / "keyring.json"
    initialize_keyring_file(keyring)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=keyring,
    )
    authentication = FakeAuthentication()
    service = FakeReauthenticationService()
    with TestClient(create_app(settings)) as test_client:
        test_client.app.state.operator_authentication = authentication
        test_client.app.state.banking_pluggy_reauthentication = service
        yield test_client, authentication, service


def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def assert_no_store(response: httpx.Response) -> None:
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_reauthentication_derives_scope_and_returns_only_ephemeral_widget_fields(
    client: tuple[TestClient, FakeAuthentication, FakeReauthenticationService],
) -> None:
    test_client, _, service = client
    response = test_client.post(PATH, headers=headers())

    assert response.status_code == 200
    assert response.json() == {
        "accessToken": CONNECT_TOKEN,
        "itemId": ITEM_ID,
    }
    assert service.calls == [(INSTALLATION_ID, RESIDENCE_ID, CONNECTION_ID)]
    assert str(INSTALLATION_ID) not in response.text
    assert str(RESIDENCE_ID) not in response.text
    assert_no_store(response)


def test_reauthentication_requires_admin_session_and_residence(
    client: tuple[TestClient, FakeAuthentication, FakeReauthenticationService],
) -> None:
    test_client, authentication, service = client

    unauthenticated = test_client.post(PATH)
    authentication.principal = principal(admin=False)
    forbidden = test_client.post(PATH, headers=headers())
    authentication.principal = principal(residence_id=None)
    missing_residence = test_client.post(PATH, headers=headers())

    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403
    assert missing_residence.status_code == 409
    assert service.calls == []
    for response in (unauthenticated, forbidden, missing_residence):
        assert_no_store(response)


def test_reauthentication_rejects_body_and_query_parameters(
    client: tuple[TestClient, FakeAuthentication, FakeReauthenticationService],
) -> None:
    test_client, _, service = client

    body = test_client.post(PATH, headers=headers(), json={"itemId": ITEM_ID})
    query = test_client.post(
        PATH,
        headers=headers(),
        params={"residence_id": str(RESIDENCE_ID)},
    )

    assert body.status_code == 422
    assert query.status_code == 422
    assert body.json() == {"detail": "request body is not allowed"}
    assert query.json() == {"detail": "query parameters are not allowed"}
    assert service.calls == []
    assert_no_store(body)
    assert_no_store(query)


def test_reauthentication_rejects_invalid_local_connection_uuid(
    client: tuple[TestClient, FakeAuthentication, FakeReauthenticationService],
) -> None:
    test_client, _, service = client
    path = "/api/v1/banking/pluggy/connections/not-a-uuid/reauthentication-token"
    response = test_client.post(path, headers=headers())

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid banking request"}
    assert service.calls == []
    assert_no_store(response)


def test_reauthentication_is_unavailable_without_runtime_service(
    client: tuple[TestClient, FakeAuthentication, FakeReauthenticationService],
) -> None:
    test_client, _, service = client
    test_client.app.state.banking_pluggy_reauthentication = None
    response = test_client.post(PATH, headers=headers())

    assert response.status_code == 404
    assert response.json() == {"detail": "banking provider is unavailable"}
    assert service.calls == []
    assert_no_store(response)


@pytest.mark.parametrize(
    ("code", "status_code"),
    [
        (PluggyReauthenticationErrorCode.CONNECTION_NOT_FOUND, 404),
        (PluggyReauthenticationErrorCode.CONNECTION_NOT_AVAILABLE, 409),
        (PluggyReauthenticationErrorCode.CONNECTION_NOT_ALLOWED, 403),
        (PluggyReauthenticationErrorCode.CONFIGURATION_REQUIRED, 409),
        (PluggyReauthenticationErrorCode.PROVIDER_NOT_ENABLED, 409),
        (PluggyReauthenticationErrorCode.ITEM_UNAVAILABLE, 404),
        (PluggyReauthenticationErrorCode.INVALID_PROVIDER_RESPONSE, 502),
        (PluggyReauthenticationErrorCode.PROVIDER_REJECTED, 502),
        (PluggyReauthenticationErrorCode.TEMPORARILY_UNAVAILABLE, 503),
        (PluggyReauthenticationErrorCode.INTERNAL, 503),
    ],
)
def test_reauthentication_errors_have_stable_http_mapping(
    client: tuple[TestClient, FakeAuthentication, FakeReauthenticationService],
    code: PluggyReauthenticationErrorCode,
    status_code: int,
) -> None:
    test_client, _, service = client
    service.error = PluggyReauthenticationError(code)
    response = test_client.post(PATH, headers=headers())

    assert response.status_code == status_code
    assert ITEM_ID not in response.text
    assert CONNECT_TOKEN not in response.text
    assert str(INSTALLATION_ID) not in response.text
    assert str(RESIDENCE_ID) not in response.text
    assert_no_store(response)


def test_reauthentication_openapi_has_only_local_connection_path_parameter(
    client: tuple[TestClient, FakeAuthentication, FakeReauthenticationService],
) -> None:
    test_client, _, _ = client
    schema = test_client.get("/api/v1/openapi.json").json()
    template = (
        "/api/v1/banking/pluggy/connections/{connection_id}/reauthentication-token"
    )
    operation = schema["paths"][template]["post"]

    assert "requestBody" not in operation
    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "connection_id"
    ]
    assert operation["parameters"][0]["in"] == "path"
