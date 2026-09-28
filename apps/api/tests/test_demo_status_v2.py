from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from meufinanceiro_persistence import DEMO_CONTRACT_CHECKSUM
from meufinanceiro_security.keyring import initialize_keyring_file

from app.core.config import Settings
from app.main import create_app


def test_disabled_demo_status_uses_finance_v2_contract(tmp_path: Path) -> None:
    keyring = tmp_path / "keyring.json"
    initialize_keyring_file(keyring)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=keyring,
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/demo/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False
    assert payload["loaded"] is False
    assert payload["fixture_id"] == "residencia-ipe-v1"
    assert payload["fixture_version"] == 2
    assert payload["scope"] == "finance_phase1"
    assert payload["contract_checksum"] == DEMO_CONTRACT_CHECKSUM


def test_demo_status_openapi_is_get_only(tmp_path: Path) -> None:
    keyring = tmp_path / "keyring.json"
    initialize_keyring_file(keyring)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=keyring,
    )

    with TestClient(create_app(settings)) as client:
        document = client.get("/api/v1/openapi.json").json()

    assert set(document["paths"]["/api/v1/demo/status"]) == {"get"}
