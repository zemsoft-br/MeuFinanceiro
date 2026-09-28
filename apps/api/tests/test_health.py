from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from meufinanceiro_persistence.health import PersistenceHealth
from meufinanceiro_security.errors import KeyringError

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    from meufinanceiro_security.keyring import initialize_keyring_file

    keyring = tmp_path / "keyring.json"
    initialize_keyring_file(keyring)
    return Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=keyring,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_liveness(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "api",
        "process": "ok",
    }


def test_readiness_reports_database_and_schema_separately(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.routes.health.inspect_persistence_health",
        lambda _engine: PersistenceHealth(
            database="ok",
            schema="ok",
            current_revision="0001_persistence_queue",
            expected_revision="0001_persistence_queue",
        ),
    )

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "api",
        "process": "ok",
        "database": "ok",
        "schema": "ok",
        "current_revision": "0001_persistence_queue",
        "expected_revision": "0001_persistence_queue",
    }


def test_readiness_reports_schema_mismatch(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.routes.health.inspect_persistence_health",
        lambda _engine: PersistenceHealth(
            database="ok",
            schema="outdated",
            current_revision=None,
            expected_revision="0001_persistence_queue",
        ),
    )

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["schema"] == "outdated"
    assert response.json()["database"] == "ok"


def test_readiness_reports_database_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.routes.health.inspect_persistence_health",
        lambda _engine: PersistenceHealth(
            database="unavailable",
            schema="unavailable",
            current_revision=None,
            expected_revision="0001_persistence_queue",
        ),
    )

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"


def test_startup_rejects_missing_keyring(tmp_path: Path) -> None:
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=tmp_path / "missing-keyring.json",
    )

    with pytest.raises(KeyringError, match="does not exist"):
        with TestClient(create_app(settings)):
            pass
