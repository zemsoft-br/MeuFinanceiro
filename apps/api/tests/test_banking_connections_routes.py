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
    PluggyConnectionRegistrationError,
    PluggyConnectionRegistrationErrorCode,
    RegisteredPluggyConnection,
)
from meufinanceiro_persistence import (
    OperatorRole,
    OperatorSessionPrincipal,
    StoredConnectionStatus,
)
from meufinanceiro_security.keyring import initialize_keyring_file

from app.core.config import Settings
from app.main import create_app
from app.services.operator_auth import InvalidOperatorSessionError

TOKEN = "R" * 43
ITEM_ID = "synthetic-item-123"
INSTALLATION_ID = UUID("10000000-0000-4000-8000-000000000001")
RESIDENCE_ID = UUID("20000000-0000-4000-8000-000000000002")
OPERATOR_ID = UUID("30000000-0000-4000-8000-000000000003")
CONNECTION_ID = UUID("40000000-0000-4000-8000-000000000004")
NOW = datetime(2026, 8, 7, tzinfo=UTC)
PATH = "/api/v1/banking/pluggy/connections"


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


class FakeRegistrationService:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID, str]] = []
        self.error: PluggyConnectionRegistrationError | None = None

    def register(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        item_id: str,
    ) -> RegisteredPluggyConnection:
        self.calls.append((installation_id, residence_id, item_id))
        if self.error is not None:
            raise self.error
        return RegisteredPluggyConnection(
            connection_id=CONNECTION_ID,
            status=StoredConnectionStatus.AVAILABLE,
            requires_user_action=False,
        )


@pytest.fixture
def client(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, FakeAuthentication, FakeRegistrationService]]:
    keyring = tmp_path / "keyring.json"
    initialize_keyring_file(keyring)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=keyring,
    )
    authentication = FakeAuthentication()
    service = FakeRegistrationService()
    with TestClient(create_app(settings)) as test_client:
        test_client.app.state.operator_authentication = authentication
        test_client.app.state.banking_pluggy_connection_registration = service
        yield test_client, authentication, service


def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def assert_no_store(response: httpx.Response) -> None:
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_registration_derives_scope_and_returns_only_local_fields(
    client: tuple[TestClient, FakeAuthentication, FakeRegistrationService],
) -> None:
    test_client, _, service = client
    response = test_client.post(PATH, headers=headers(), json={"itemId": ITEM_ID})

    assert response.status_code == 200
    assert response.json() == {
        "connectionId": str(CONNECTION_ID),
        "status": "AVAILABLE",
        "requiresUserAction": False,
    }
    assert service.calls == [(INSTALLATION_ID, RESIDENCE_ID, ITEM_ID)]
    assert ITEM_ID not in response.text
    assert str(INSTALLATION_ID) not in response.text
    assert str(RESIDENCE_ID) not in response.text
    assert_no_store(response)


def test_registration_requires_admin_session_and_residence(
    client: tuple[TestClient, FakeAuthentication, FakeRegistrationService],
) -> None:
    test_client, authentication, service = client

    unauthenticated = test_client.post(PATH, json={"itemId": ITEM_ID})
    authentication.principal = principal(admin=False)
    forbidden = test_client.post(PATH, headers=headers(), json={"itemId": ITEM_ID})
    authentication.principal = principal(residence_id=None)
    missing_residence = test_client.post(
        PATH,
        headers=headers(),
        json={"itemId": ITEM_ID},
    )

    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403
    assert missing_residence.status_code == 409
    assert service.calls == []
    for response in (unauthenticated, forbidden, missing_residence):
        assert_no_store(response)


@pytest.mark.parametrize(
    "payload",
    [
        {"item_id": ITEM_ID},
        {"itemId": ITEM_ID, "residence_id": str(RESIDENCE_ID)},
        {"itemId": ITEM_ID, "installation_id": str(INSTALLATION_ID)},
        {"itemId": ITEM_ID, "clientUserId": f"residence:{RESIDENCE_ID}"},
        {"itemId": ITEM_ID, "status": "AVAILABLE"},
        {"itemId": ITEM_ID, "capabilities": []},
    ],
)
def test_registration_accepts_only_item_id_wire_field(
    client: tuple[TestClient, FakeAuthentication, FakeRegistrationService],
    payload: dict[str, object],
) -> None:
    test_client, _, service = client
    response = test_client.post(PATH, headers=headers(), json=payload)

    assert response.status_code == 422
    assert service.calls == []
    assert_no_store(response)


def test_registration_rejects_query_parameters(
    client: tuple[TestClient, FakeAuthentication, FakeRegistrationService],
) -> None:
    test_client, _, service = client
    response = test_client.post(
        PATH,
        headers=headers(),
        params={"residence_id": str(RESIDENCE_ID)},
        json={"itemId": ITEM_ID},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "query parameters are not allowed"}
    assert service.calls == []
    assert_no_store(response)


def test_registration_is_unavailable_without_runtime_service(
    client: tuple[TestClient, FakeAuthentication, FakeRegistrationService],
) -> None:
    test_client, _, service = client
    test_client.app.state.banking_pluggy_connection_registration = None
    response = test_client.post(PATH, headers=headers(), json={"itemId": ITEM_ID})

    assert response.status_code == 404
    assert response.json() == {"detail": "banking provider is unavailable"}
    assert service.calls == []
    assert_no_store(response)


@pytest.mark.parametrize(
    ("code", "status_code"),
    [
        (PluggyConnectionRegistrationErrorCode.CONFIGURATION_REQUIRED, 409),
        (PluggyConnectionRegistrationErrorCode.PROVIDER_NOT_ENABLED, 409),
        (PluggyConnectionRegistrationErrorCode.CONNECTION_CONFLICT, 409),
        (PluggyConnectionRegistrationErrorCode.ITEM_NOT_ALLOWED, 403),
        (PluggyConnectionRegistrationErrorCode.ITEM_UNAVAILABLE, 404),
        (PluggyConnectionRegistrationErrorCode.INVALID_PROVIDER_RESPONSE, 502),
        (PluggyConnectionRegistrationErrorCode.PROVIDER_REJECTED, 502),
        (PluggyConnectionRegistrationErrorCode.TEMPORARILY_UNAVAILABLE, 503),
        (PluggyConnectionRegistrationErrorCode.INTERNAL, 503),
    ],
)
def test_registration_errors_have_stable_http_mapping(
    client: tuple[TestClient, FakeAuthentication, FakeRegistrationService],
    code: PluggyConnectionRegistrationErrorCode,
    status_code: int,
) -> None:
    test_client, _, service = client
    service.error = PluggyConnectionRegistrationError(code)
    response = test_client.post(PATH, headers=headers(), json={"itemId": ITEM_ID})

    assert response.status_code == status_code
    assert ITEM_ID not in response.text
    assert str(INSTALLATION_ID) not in response.text
    assert str(RESIDENCE_ID) not in response.text
    assert_no_store(response)


def test_registration_openapi_exposes_only_item_id_request_field(
    client: tuple[TestClient, FakeAuthentication, FakeRegistrationService],
) -> None:
    test_client, _, _ = client
    schema = test_client.get("/api/v1/openapi.json").json()
    operation = schema["paths"][PATH]["post"]
    body_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    schema_name = body_schema["$ref"].rsplit("/", 1)[-1]
    request_schema = schema["components"]["schemas"][schema_name]

    assert set(request_schema["properties"]) == {"itemId"}
    assert request_schema["additionalProperties"] is False
