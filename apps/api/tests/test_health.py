from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from meufinanceiro_security.errors import KeyringError

from app.core.config import Settings
from app.main import app, create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def test_liveness(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "api"}


def test_readiness(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.routes.health.check_database", lambda: None)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "api",
        "database": "ok",
    }


def test_readiness_reports_database_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("app.api.routes.health.check_database", fail)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "database_unavailable"


def test_startup_rejects_missing_keyring(tmp_path) -> None:
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=tmp_path / "missing-keyring.json",
    )

    with pytest.raises(KeyringError, match="does not exist"):
        with TestClient(create_app(settings)):
            pass
