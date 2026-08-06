from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from meufinanceiro_persistence import (
    OperatorRole,
    OperatorSessionPrincipal,
    ProviderConfigurationRecord,
    ProviderConfigurationState,
)
from meufinanceiro_security.keyring import initialize_keyring_file

from app.core.config import Settings
from app.main import create_app
from app.services.banking_admin import (
    BankingAdministrationError,
    BankingAdministrationErrorCode,
)
from app.services.operator_auth import InvalidOperatorSessionError

TOKEN = "A" * 43
INSTALLATION_ID = UUID("10000000-0000-4000-8000-000000000001")
OPERATOR_ID = UUID("20000000-0000-4000-8000-000000000002")
CONFIGURATION_ID = UUID("30000000-0000-4000-8000-000000000003")
NOW = datetime(2026, 8, 6, tzinfo=UTC)
CLIENT_ID = "sensitive-client-id"
CLIENT_SECRET = "sensitive-client-secret"


def principal(*, admin: bool = True) -> OperatorSessionPrincipal:
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
    )


def configuration(
    *,
    state: ProviderConfigurationState = ProviderConfigurationState.CONFIGURED,
    revision: int = 1,
) -> ProviderConfigurationRecord:
    return ProviderConfigurationRecord(
        id=CONFIGURATION_ID,
        installation_id=INSTALLATION_ID,
        provider="pluggy",
        state=state,
        configuration_revision=revision,
        created_at=NOW,
        updated_at=NOW,
        enabled_at=NOW if state is ProviderConfigurationState.ENABLED else None,
        disabled_at=NOW if state is ProviderConfigurationState.DISABLED else None,
    )


class FakeAuthentication:
    def __init__(self) -> None:
        self.principal = principal()

    def resolve(self, token: str) -> OperatorSessionPrincipal:
        if token != TOKEN:
            raise InvalidOperatorSessionError("operator session is invalid")
        return self.principal


class FakeAdministration:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.error: BankingAdministrationError | None = None
        self.record = configuration()

    def _result(self, *call: object) -> ProviderConfigurationRecord:
        self.calls.append(call)
        if self.error is not None:
            raise self.error
        return self.record

    def configure_provider(
        self,
        *,
        installation_id: UUID,
        provider: str,
        client_id: str,
        client_secret: str,
    ) -> ProviderConfigurationRecord:
        return self._result(
            "configure",
            installation_id,
            provider,
            client_id,
            client_secret,
        )

    def get_provider_configuration(
        self,
        *,
        installation_id: UUID,
        provider: str,
    ) -> ProviderConfigurationRecord:
        return self._result("get", installation_id, provider)

    def replace_provider_credentials(
        self,
        *,
        installation_id: UUID,
        provider: str,
        expected_revision: int,
        client_id: str,
        client_secret: str,
    ) -> ProviderConfigurationRecord:
        return self._result(
            "replace",
            installation_id,
            provider,
            expected_revision,
            client_id,
            client_secret,
        )

    def set_provider_state(
        self,
        *,
        installation_id: UUID,
        provider: str,
        expected_revision: int,
        state: ProviderConfigurationState,
    ) -> ProviderConfigurationRecord:
        return self._result(
            "state",
            installation_id,
            provider,
            expected_revision,
            state,
        )


@pytest.fixture
def client(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, FakeAuthentication, FakeAdministration]]:
    keyring = tmp_path / "keyring.json"
    initialize_keyring_file(keyring)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=keyring,
    )
    authentication = FakeAuthentication()
    administration = FakeAdministration()
    with TestClient(create_app(settings)) as test_client:
        test_client.app.state.operator_authentication = authentication
        test_client.app.state.banking_administration = administration
        yield test_client, authentication, administration


def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def assert_sanitized_response(response_text: str) -> None:
    assert CLIENT_ID not in response_text
    assert CLIENT_SECRET not in response_text
    assert str(INSTALLATION_ID) not in response_text


def test_all_administration_routes_require_authentication(
    client: tuple[TestClient, FakeAuthentication, FakeAdministration],
) -> None:
    test_client, _, _ = client
    requests = (
        ("post", "/api/v1/admin/banking/providers/pluggy/configuration", {}),
        ("get", "/api/v1/admin/banking/providers/pluggy/configuration", None),
        ("put", "/api/v1/admin/banking/providers/pluggy/credentials", {}),
        ("patch", "/api/v1/admin/banking/providers/pluggy/state", {}),
    )
    for method, path, payload in requests:
        response = test_client.request(method, path, json=payload)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.headers["cache-control"] == "no-store"


def test_non_admin_operator_is_forbidden(
    client: tuple[TestClient, FakeAuthentication, FakeAdministration],
) -> None:
    test_client, authentication, administration = client
    authentication.principal = principal(admin=False)

    response = test_client.get(
        "/api/v1/admin/banking/providers/pluggy/configuration",
        headers=headers(),
    )

    assert response.status_code == 403
    assert administration.calls == []


def test_configure_derives_installation_and_never_returns_credentials(
    client: tuple[TestClient, FakeAuthentication, FakeAdministration],
) -> None:
    test_client, _, administration = client

    response = test_client.post(
        "/api/v1/admin/banking/providers/pluggy/configuration",
        headers=headers(),
        json={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
    )

    assert response.status_code == 201
    assert administration.calls == [
        ("configure", INSTALLATION_ID, "pluggy", CLIENT_ID, CLIENT_SECRET)
    ]
    assert response.json()["configuration_id"] == str(CONFIGURATION_ID)
    assert "installation_id" not in response.json()
    assert "client_id" not in response.json()
    assert "client_secret" not in response.json()
    assert_sanitized_response(response.text)


def test_get_replace_and_state_use_authenticated_installation(
    client: tuple[TestClient, FakeAuthentication, FakeAdministration],
) -> None:
    test_client, _, administration = client

    get_response = test_client.get(
        "/api/v1/admin/banking/providers/pluggy/configuration",
        headers=headers(),
    )
    replace_response = test_client.put(
        "/api/v1/admin/banking/providers/pluggy/credentials",
        headers=headers(),
        json={
            "expected_revision": 1,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )
    state_response = test_client.patch(
        "/api/v1/admin/banking/providers/pluggy/state",
        headers=headers(),
        json={"expected_revision": 1, "state": "disabled"},
    )

    assert get_response.status_code == 200
    assert replace_response.status_code == 200
    assert state_response.status_code == 200
    assert administration.calls == [
        ("get", INSTALLATION_ID, "pluggy"),
        (
            "replace",
            INSTALLATION_ID,
            "pluggy",
            1,
            CLIENT_ID,
            CLIENT_SECRET,
        ),
        (
            "state",
            INSTALLATION_ID,
            "pluggy",
            1,
            ProviderConfigurationState.DISABLED,
        ),
    ]
    for response in (get_response, replace_response, state_response):
        assert_sanitized_response(response.text)
        assert response.headers["cache-control"] == "no-store"


def test_payload_forbids_context_and_unknown_fields(
    client: tuple[TestClient, FakeAuthentication, FakeAdministration],
) -> None:
    test_client, _, administration = client

    response = test_client.post(
        "/api/v1/admin/banking/providers/pluggy/configuration",
        headers=headers(),
        json={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "installation_id": str(uuid4()),
        },
    )

    assert response.status_code == 422
    assert administration.calls == []
    assert_sanitized_response(response.text)


@pytest.mark.parametrize(
    ("code", "status_code"),
    [
        (BankingAdministrationErrorCode.PROVIDER_UNAVAILABLE, 404),
        (BankingAdministrationErrorCode.CONFIGURATION_NOT_FOUND, 404),
        (BankingAdministrationErrorCode.FEATURE_DISABLED, 409),
        (BankingAdministrationErrorCode.CONFIGURATION_CONFLICT, 409),
        (BankingAdministrationErrorCode.PERSISTENCE_FAILURE, 503),
    ],
)
def test_service_errors_have_stable_http_mapping(
    client: tuple[TestClient, FakeAuthentication, FakeAdministration],
    code: BankingAdministrationErrorCode,
    status_code: int,
) -> None:
    test_client, _, administration = client
    administration.error = BankingAdministrationError(code, "safe administration error")

    response = test_client.get(
        "/api/v1/admin/banking/providers/unsafe-provider/configuration",
        headers=headers(),
    )

    assert response.status_code == status_code
    assert response.json() == {"detail": "safe administration error"}
    assert response.headers["cache-control"] == "no-store"


def test_openapi_request_schemas_contain_no_context_or_secret_examples(
    client: tuple[TestClient, FakeAuthentication, FakeAdministration],
) -> None:
    test_client, _, _ = client
    schema = test_client.get("/api/v1/openapi.json").json()
    components = schema["components"]["schemas"]

    for model_name in (
        "ConfigureProviderRequest",
        "ReplaceProviderCredentialsRequest",
        "SetProviderStateRequest",
    ):
        properties = components[model_name]["properties"]
        assert "installation_id" not in properties
        assert "operator_id" not in properties
        assert "session_id" not in properties

    serialized = str(schema)
    assert CLIENT_ID not in serialized
    assert CLIENT_SECRET not in serialized
