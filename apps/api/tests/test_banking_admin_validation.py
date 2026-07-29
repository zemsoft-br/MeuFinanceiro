from __future__ import annotations

from typing import NoReturn
from uuid import UUID, uuid4

import pytest
from meufinanceiro_banking import BankingProviderRegistry
from meufinanceiro_persistence import (
    ProviderConfigurationRecord,
    ProviderConfigurationState,
)

from app.services.banking_admin import (
    BankingAdministrationError,
    BankingAdministrationErrorCode,
    BankingAdministrationService,
)


class UnexpectedStore:
    @staticmethod
    def _unexpected() -> NoReturn:
        raise AssertionError("persistence must not be called for an invalid provider")

    def create_configuration(
        self,
        *,
        installation_id: UUID,
        provider: str,
        client_id: str,
        client_secret: str,
    ) -> ProviderConfigurationRecord:
        del installation_id, provider, client_id, client_secret
        self._unexpected()

    def get_configuration(
        self,
        *,
        installation_id: UUID,
        provider: str,
    ) -> ProviderConfigurationRecord:
        del installation_id, provider
        self._unexpected()

    def replace_credentials(
        self,
        *,
        installation_id: UUID,
        provider: str,
        expected_revision: int,
        client_id: str,
        client_secret: str,
    ) -> ProviderConfigurationRecord:
        del installation_id, provider, expected_revision, client_id, client_secret
        self._unexpected()

    def set_configuration_state(
        self,
        *,
        installation_id: UUID,
        provider: str,
        expected_revision: int,
        state: ProviderConfigurationState,
    ) -> ProviderConfigurationRecord:
        del installation_id, provider, expected_revision, state
        self._unexpected()


@pytest.mark.parametrize(
    "operation",
    ["configure", "get", "replace", "disable"],
)
def test_invalid_provider_name_is_mapped_to_stable_error(operation: str) -> None:
    service = BankingAdministrationService(
        UnexpectedStore(),
        BankingProviderRegistry().freeze(),
        feature_enabled=True,
    )
    installation_id = uuid4()

    with pytest.raises(BankingAdministrationError) as captured:
        if operation == "configure":
            service.configure_provider(
                installation_id=installation_id,
                provider="unsafe provider\nsecret",
                client_id="client",
                client_secret="secret",
            )
        elif operation == "get":
            service.get_provider_configuration(
                installation_id=installation_id,
                provider="unsafe provider\nsecret",
            )
        elif operation == "replace":
            service.replace_provider_credentials(
                installation_id=installation_id,
                provider="unsafe provider\nsecret",
                expected_revision=1,
                client_id="client",
                client_secret="secret",
            )
        else:
            service.set_provider_state(
                installation_id=installation_id,
                provider="unsafe provider\nsecret",
                expected_revision=1,
                state=ProviderConfigurationState.DISABLED,
            )

    assert captured.value.code is BankingAdministrationErrorCode.PROVIDER_UNAVAILABLE
    assert str(captured.value) == "banking provider is unavailable"
    assert "unsafe" not in str(captured.value)
    assert captured.value.__cause__ is None
