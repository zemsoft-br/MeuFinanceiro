from __future__ import annotations

from datetime import UTC, datetime
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

NOW = datetime(2026, 8, 4, tzinfo=UTC)


def configuration_record(
    *,
    installation_id: UUID,
    provider: str = "pluggy",
    state: ProviderConfigurationState = ProviderConfigurationState.CONFIGURED,
) -> ProviderConfigurationRecord:
    return ProviderConfigurationRecord(
        id=uuid4(),
        installation_id=installation_id,
        provider=provider,
        state=state,
        configuration_revision=1,
        created_at=NOW,
        updated_at=NOW,
        enabled_at=NOW if state is ProviderConfigurationState.ENABLED else None,
        disabled_at=NOW if state is ProviderConfigurationState.DISABLED else None,
    )


class StoreStub:
    def __init__(self, record: ProviderConfigurationRecord) -> None:
        self.record = record
        self.calls: list[tuple[str, str]] = []

    def create_configuration(
        self,
        *,
        installation_id: UUID,
        provider: str,
        client_id: str,
        client_secret: str,
    ) -> ProviderConfigurationRecord:
        del installation_id, client_id, client_secret
        self.calls.append(("create", provider))
        return self.record

    def get_configuration(
        self,
        *,
        installation_id: UUID,
        provider: str,
    ) -> ProviderConfigurationRecord:
        del installation_id
        self.calls.append(("get", provider))
        return self.record

    def replace_credentials(
        self,
        *,
        installation_id: UUID,
        provider: str,
        expected_revision: int,
        client_id: str,
        client_secret: str,
    ) -> ProviderConfigurationRecord:
        del installation_id, expected_revision, client_id, client_secret
        self.calls.append(("replace", provider))
        return self.record

    def set_configuration_state(
        self,
        *,
        installation_id: UUID,
        provider: str,
        expected_revision: int,
        state: ProviderConfigurationState,
    ) -> ProviderConfigurationRecord:
        del installation_id, expected_revision, state
        self.calls.append(("state", provider))
        return self.record


def test_explicit_provider_catalog_does_not_require_registry_factory() -> None:
    installation_id = uuid4()
    expected = configuration_record(installation_id=installation_id)
    store = StoreStub(expected)
    service = BankingAdministrationService(
        store,
        BankingProviderRegistry().freeze(),
        feature_enabled=True,
        available_providers=("pluggy",),
    )

    actual = service.configure_provider(
        installation_id=installation_id,
        provider="pluggy",
        client_id="client",
        client_secret="secret",
    )

    assert actual is expected
    assert service.available_providers == ("pluggy",)
    assert store.calls == [("create", "pluggy")]


def test_provider_can_be_configured_but_not_enabled_when_global_flag_is_off() -> None:
    installation_id = uuid4()
    expected = configuration_record(installation_id=installation_id)
    store = StoreStub(expected)
    service = BankingAdministrationService(
        store,
        BankingProviderRegistry().freeze(),
        feature_enabled=False,
        available_providers=("pluggy",),
    )

    service.configure_provider(
        installation_id=installation_id,
        provider="pluggy",
        client_id="client",
        client_secret="secret",
    )
    with pytest.raises(BankingAdministrationError) as captured:
        service.set_provider_state(
            installation_id=installation_id,
            provider="pluggy",
            expected_revision=1,
            state=ProviderConfigurationState.ENABLED,
        )

    assert captured.value.code is BankingAdministrationErrorCode.FEATURE_DISABLED
    assert store.calls == [("create", "pluggy")]


def test_provider_outside_explicit_catalog_is_rejected_before_persistence() -> None:
    installation_id = uuid4()
    store = StoreStub(configuration_record(installation_id=installation_id))
    service = BankingAdministrationService(
        store,
        BankingProviderRegistry().freeze(),
        feature_enabled=True,
        available_providers=("pluggy",),
    )

    with pytest.raises(BankingAdministrationError) as captured:
        service.replace_provider_credentials(
            installation_id=installation_id,
            provider="fake",
            expected_revision=1,
            client_id="client",
            client_secret="secret",
        )

    assert captured.value.code is BankingAdministrationErrorCode.PROVIDER_UNAVAILABLE
    assert store.calls == []


def test_registry_remains_default_catalog_when_explicit_catalog_is_omitted() -> None:
    service = BankingAdministrationService(
        StoreStub(configuration_record(installation_id=uuid4())),
        BankingProviderRegistry().freeze(),
        feature_enabled=True,
    )

    assert service.available_providers == ()


def test_invalid_explicit_catalog_fails_closed() -> None:
    with pytest.raises(ValueError, match="available providers"):
        BankingAdministrationService(
            StoreStub(configuration_record(installation_id=uuid4())),
            BankingProviderRegistry().freeze(),
            feature_enabled=True,
            available_providers=("unsafe provider",),
        )
