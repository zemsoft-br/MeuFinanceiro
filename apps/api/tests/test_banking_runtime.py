from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from meufinanceiro_banking import BankingProviderRegistry
from meufinanceiro_security.keyring import initialize_keyring_file

from app.core.config import Settings
from app.main import create_app
from app.services.banking_admin import BankingAdministrationService


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
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


def test_banking_runtime_is_empty_frozen_and_disabled_by_default(
    client: TestClient,
) -> None:
    registry = client.app.state.banking_provider_registry
    administration = client.app.state.banking_administration

    assert isinstance(registry, BankingProviderRegistry)
    assert registry.names() == ()
    assert registry.frozen is True
    assert isinstance(administration, BankingAdministrationService)
    assert administration.feature_enabled is False


def test_settings_require_explicit_banking_enablement(tmp_path: Path) -> None:
    keyring = tmp_path / "keyring.json"
    initialize_keyring_file(keyring)

    disabled = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=keyring,
    )
    enabled = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=keyring,
        app_banking_enabled=True,
    )

    assert disabled.app_banking_enabled is False
    assert enabled.app_banking_enabled is True
