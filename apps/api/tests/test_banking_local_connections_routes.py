from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from meufinanceiro_persistence import OperatorRole, OperatorSessionPrincipal
from meufinanceiro_security.keyring import initialize_keyring_file

from app.core.config import Settings
from app.main import create_app
from app.services.banking_connections import LocalBankingConnectionSummary
from app.services.operator_auth import InvalidOperatorSessionError
from meufinanceiro_persistence import StoredConnectionStatus

TOKEN = "L" * 43
INSTALLATION_ID = UUID("10000000-0000-4000-8000-000000000001")
RESIDENCE_ID = UUID("20000000-0000-4000-8000-000000000002")
OPERATOR_ID = UUID("30000000-0000-4000-8000-000000000003")
CONNECTION_ID = UUID("40000000-0000-4000-8000-000000000004")
NOW = datetime(2026, 8, 8, tzinfo=UTC)
PATH = "/api/v1/banking/connections"


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
        expires_at=datetime(2027, 8, 8, tzinfo=UTC),
        primary_residence_id=residence_id,
    )


class FakeAuthentication:
    def __init__(self) -> None:
        self.principal = principal()

    def resolve(self, token: str) -> OperatorSessionPrincipal:
        if token != TOKEN:
            raise InvalidOperatorSessionError("operator session is invalid")
        return self.principal


class FakeConnectionsService:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID]] = []
        self.connections: tuple[LocalBankingConnectionSummary, ...] = (
            LocalBankingConnectionSummary(
                connection_id=CONNECTION_ID,
                provider="pluggy",
                status=StoredConnectionStatus.REAUTHENTICATION_REQUIRED,
                requires_user_action=True,
                last_successful_sync_at=None,
                last_attempt_at=NOW,
                next_refresh_allowed_at=None,
                consent_expires_at=None,
                disconnected_at=None,
                updated_at=NOW,
                reauthentication_available=True,
            ),
        )

    def list_connections(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
    ) -> tuple[LocalBankingConnectionSummary, ...]:
        self.calls.append((installation_id, residence_id))
        return self.connections


@pytest.fixture
def client(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, FakeAuthentication, FakeConnectionsService]]:
    keyring = tmp_path / "keyring.json"
    initialize_keyring_file(keyring)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=keyring,
    )
    authentication = FakeAuthentication()
    service = FakeConnectionsService()
    with TestClient(create_app(settings)) as test_client:
        test_client.app.state.operator_authentication = authentication
        test_client.app.state.banking_connections = service
        yield test_client, authentication, service


def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def assert_no_store(response: httpx.Response) -> None:
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_list_derives_residence_scope_and_returns_only_local_metadata(
    client: tuple[TestClient, FakeAuthentication, FakeConnectionsService],
) -> None:
    test_client, _, service = client
    response = test_client.get(PATH, headers=headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "connections": [
            {
                "connectionId": str(CONNECTION_ID),
                "provider": "pluggy",
                "status": "REAUTHENTICATION_REQUIRED",
                "requiresUserAction": True,
                "lastSuccessfulSyncAt": None,
                "lastAttemptAt": "2026-08-08T00:00:00Z",
                "nextRefreshAllowedAt": None,
                "consentExpiresAt": None,
                "disconnectedAt": None,
                "updatedAt": "2026-08-08T00:00:00Z",
                "reauthenticationAvailable": True,
            }
        ]
    }
    assert service.calls == [(INSTALLATION_ID, RESIDENCE_ID)]
    serialized = response.text
    for forbidden in (
        "external_connection_id",
        "externalConnectionId",
        "itemId",
        "clientUserId",
        "provider_reason_code",
        "providerReasonCode",
        "credential",
        "apiKey",
        "accessToken",
    ):
        assert forbidden not in serialized
    assert_no_store(response)


def test_empty_connection_list_is_canonical(
    client: tuple[TestClient, FakeAuthentication, FakeConnectionsService],
) -> None:
    test_client, _, service = client
    service.connections = ()

    response = test_client.get(PATH, headers=headers())

    assert response.status_code == 200
    assert response.json() == {"connections": []}
    assert_no_store(response)


def test_list_requires_admin_session_and_primary_residence(
    client: tuple[TestClient, FakeAuthentication, FakeConnectionsService],
) -> None:
    test_client, authentication, service = client

    unauthenticated = test_client.get(PATH)
    authentication.principal = principal(admin=False)
    forbidden = test_client.get(PATH, headers=headers())
    authentication.principal = principal(residence_id=None)
    missing_residence = test_client.get(PATH, headers=headers())

    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403
    assert missing_residence.status_code == 409
    assert service.calls == []
    for response in (unauthenticated, forbidden, missing_residence):
        assert_no_store(response)


def test_list_rejects_query_and_body(
    client: tuple[TestClient, FakeAuthentication, FakeConnectionsService],
) -> None:
    test_client, _, service = client

    query = test_client.get(PATH, headers=headers(), params={"provider": "pluggy"})
    body = test_client.request(
        "GET",
        PATH,
        headers=headers(),
        json={"residenceId": str(RESIDENCE_ID)},
    )

    assert query.status_code == 422
    assert body.status_code == 422
    assert service.calls == []
    assert_no_store(query)
    assert_no_store(body)


def test_openapi_exposes_no_client_controlled_scope_or_request_body(
    client: tuple[TestClient, FakeAuthentication, FakeConnectionsService],
) -> None:
    test_client, _, _ = client
    schema = test_client.get("/api/v1/openapi.json").json()
    operation = schema["paths"][PATH]["get"]

    assert "requestBody" not in operation
    assert operation.get("parameters", []) == []
