from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from meufinanceiro_banking_pluggy_execution import PluggyReadOnlyExecutionService
from meufinanceiro_persistence import BankingIntegrationStore
from meufinanceiro_security.keyring import initialize_keyring_file

import meufinanceiro_banking_pluggy_execution.service as execution_module
from app.core.config import Settings
from app.main import create_app


def runtime_settings(
    tmp_path: Path,
    *,
    banking_enabled: bool,
    pluggy_enabled: bool,
) -> Settings:
    keyring = tmp_path / f"keyring-{banking_enabled}-{pluggy_enabled}.json"
    initialize_keyring_file(keyring)
    return Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=keyring,
        app_banking_enabled=banking_enabled,
        app_banking_pluggy_enabled=pluggy_enabled,
    )


@pytest.mark.parametrize(
    (
        "banking_enabled",
        "pluggy_enabled",
        "expected_available",
        "expected_executor",
    ),
    [
        (False, False, (), False),
        (False, True, ("pluggy",), False),
        (True, False, (), False),
        (True, True, ("pluggy",), True),
    ],
)
def test_runtime_composition_is_controlled_by_both_flags(
    tmp_path: Path,
    *,
    banking_enabled: bool,
    pluggy_enabled: bool,
    expected_available: tuple[str, ...],
    expected_executor: bool,
) -> None:
    settings = runtime_settings(
        tmp_path,
        banking_enabled=banking_enabled,
        pluggy_enabled=pluggy_enabled,
    )

    with TestClient(create_app(settings)) as client:
        registry = client.app.state.banking_provider_registry
        administration = client.app.state.banking_administration
        executor = client.app.state.banking_pluggy_execution

        assert registry.names() == ()
        assert registry.frozen is True
        assert administration.feature_enabled is banking_enabled
        assert administration.available_providers == expected_available
        assert isinstance(executor, PluggyReadOnlyExecutionService) is expected_executor


def test_banking_flags_are_disabled_by_default(tmp_path: Path) -> None:
    keyring = tmp_path / "keyring.json"
    initialize_keyring_file(keyring)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        app_keyring_file=keyring,
    )

    assert settings.app_banking_enabled is False
    assert settings.app_banking_pluggy_enabled is False


def test_startup_with_both_flags_does_not_read_credentials_or_create_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_credentials(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("startup must not read banking credentials")

    def unexpected_transport(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("startup must not create Pluggy transport")

    monkeypatch.setattr(
        BankingIntegrationStore,
        "use_enabled_credentials",
        unexpected_credentials,
    )
    monkeypatch.setattr(
        execution_module,
        "PluggyGatewayHttpTransport",
        unexpected_transport,
    )
    settings = runtime_settings(
        tmp_path,
        banking_enabled=True,
        pluggy_enabled=True,
    )

    with TestClient(create_app(settings)) as client:
        assert isinstance(
            client.app.state.banking_pluggy_execution,
            PluggyReadOnlyExecutionService,
        )
