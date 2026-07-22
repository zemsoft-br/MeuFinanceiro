from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from meufinanceiro_persistence import DemoFixtureStatus

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def keyring_path(tmp_path: Path) -> Path:
    from meufinanceiro_security.keyring import initialize_keyring_file

    keyring = tmp_path / "keyring.json"
    initialize_keyring_file(keyring)
    return keyring


def test_demo_status_is_disabled_by_default(keyring_path: Path) -> None:
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=keyring_path,
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/demo/status")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "loaded": False,
        "fixture_id": "residencia-ipe-v1",
        "fixture_version": 1,
        "reference_date": "2026-11-01",
        "timezone": "America/Sao_Paulo",
        "currency": "BRL",
        "scope": "foundation_only",
        "contract_checksum": (
            "34a7628233ff6c4f5eac6469b8e80fdedd5d65d80f825b4ecf72a069235a21a1"
        ),
        "loaded_at": None,
    }


def test_demo_status_reports_loaded_fixture(
    keyring_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded_at = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "app.api.routes.demo.DemoFixtureStore.status",
        lambda _store: DemoFixtureStatus(
            enabled=True,
            loaded=True,
            fixture_id="residencia-ipe-v1",
            fixture_version=1,
            reference_date=date(2026, 11, 1),
            timezone="America/Sao_Paulo",
            currency="BRL",
            scope="foundation_only",
            contract_checksum=(
                "34a7628233ff6c4f5eac6469b8e80fdedd5d65d80f825b4ecf72a069235a21a1"
            ),
            loaded_at=loaded_at,
        ),
    )
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=keyring_path,
        app_demo_mode=True,
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/demo/status")

    payload = response.json()
    assert response.status_code == 200
    assert payload["enabled"] is True
    assert payload["loaded"] is True
    serialized_loaded_at = payload["loaded_at"].replace("Z", "+00:00")
    assert datetime.fromisoformat(serialized_loaded_at) == loaded_at


def test_openapi_exposes_only_read_only_demo_operation(keyring_path: Path) -> None:
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=keyring_path,
    )

    with TestClient(create_app(settings)) as client:
        document = client.get("/api/v1/openapi.json").json()

    operations = document["paths"]["/api/v1/demo/status"]
    assert set(operations) == {"get"}
    schema = document["components"]["schemas"]["DemoStatusResponse"]
    serialized = str(schema).lower()
    assert "password" not in serialized
    assert "database_url" not in serialized
    assert "keyring" not in serialized
