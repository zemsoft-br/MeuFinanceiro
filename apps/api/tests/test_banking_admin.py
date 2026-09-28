from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from meufinanceiro_banking import BankingProviderRegistry, FakeBankingProvider
from meufinanceiro_persistence import (
    BankingPersistenceError,
    ConfigurationConflictError,
    ConfigurationNotFoundError,
    ProviderConfigurationRecord,
    ProviderConfigurationState,
)

from app.services.banking_admin import (
    BankingAdministrationError,
    BankingAdministrationErrorCode,
    BankingAdministrationService,
)

NOW = datetime(2026, 7, 29, tzinfo=UTC)


def configuration_record(
    *,
    installation_id: UUID,
    provider: str = "fake",
    state: ProviderConfigurationState = ProviderConfigurationState.CONFIGURED,
    revision: int = 1,
) -> ProviderConfigurationRecord:
    return ProviderConfigurationRecord(
        id=uuid4(),
        installation_id=installation_id,
        provider=provider,
        state=state,
        configuration_revision=revision,
        created_at=NOW,
        updated_at=NOW,
        enabled_at=NOW if state is ProviderConfigurationState.ENABLED else None,
        disabled_at=NOW if state is ProviderConfigurationState.DISABLED else None,
    )


class StoreStub:
    def __init__(self, record: ProviderConfigurationRecord) -> None:
        self.record = record
        self.calls: list[tuple[str, str]] = []
        self.error: BankingPersistenceError | None = None

    def _result(self, operation: str, provider: str) -> ProviderConfigurationRecord:
        self.calls.append((operation, provider))
        if self.error is not None:
            raise self.error
        return self.record

    def create_configuration(
        self,
        *,
        installation_id: UUID,
        provider: str,
        client_id: str,
        client_secret: str,
    ) -> ProviderConfigurationRecord:
        del installation_id, client_id, client_secret
        return self._result("create", provider)

    def get_configuration(
        self,
        *,
        installation_id: UUID,
        provider: str,
    ) -> ProviderConfigurationRecord:
        del installation_id
        return self._result("get", provider)

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
        return self._result("replace", provider)

    def set_configuration_state(
        self,
        *,
        installation_id: UUID,
        provider: str,
        expected_revision: int,
        state: ProviderConfigurationState,
    ) -> ProviderConfigurationRecord:
        del installation_id, expected_revision, state
        return self._result("state", provider)


def registered_registry() -> BankingProviderRegistry:
    registry = BankingProviderRegistry()
    registry.register("fake", FakeBankingProvider)
    return registry.freeze()


def test_unknown_provider_cannot_be_configured_or_receive_new_credentials() -> None:
    installation_id = uuid4()
    store = StoreStub(configuration_record(installation_id=installation_id))
    service = BankingAdministrationService(
        store,
        BankingProviderRegistry().freeze(),
        feature_enabled=True,
    )

    with pytest.raises(BankingAdministrationError) as configure_error:
        service.configure_provider(
            installation_id=installation_id,
            provider="fake",
            client_id="sensitive-client",
            client_secret="sensitive-secret",
        )
    with pytest.raises(BankingAdministrationError) as replace_error:
        service.replace_provider_credentials(
            installation_id=installation_id,
            provider="fake",
            expected_revision=1,
            client_id="sensitive-client",
            client_secret="sensitive-secret",
        )

    assert (
        configure_error.value.code
        is BankingAdministrationErrorCode.PROVIDER_UNAVAILABLE
    )
    assert (
        replace_error.value.code is BankingAdministrationErrorCode.PROVIDER_UNAVAILABLE
    )
    assert "sensitive" not in str(configure_error.value)
    assert store.calls == []


def test_configuration_metadata_can_be_read_without_registered_adapter() -> None:
    installation_id = uuid4()
    expected = configuration_record(installation_id=installation_id)
    store = StoreStub(expected)
    service = BankingAdministrationService(
        store,
        BankingProviderRegistry().freeze(),
        feature_enabled=False,
    )

    actual = service.get_provider_configuration(
        installation_id=installation_id,
        provider="fake",
    )

    assert actual is expected
    assert store.calls == [("get", "fake")]
    assert not hasattr(actual, "client_id_envelope")
    assert not hasattr(actual, "client_secret_envelope")


def test_global_feature_flag_blocks_enable_before_persistence() -> None:
    installation_id = uuid4()
    store = StoreStub(configuration_record(installation_id=installation_id))
    service = BankingAdministrationService(
        store,
        registered_registry(),
        feature_enabled=False,
    )

    with pytest.raises(BankingAdministrationError) as captured:
        service.set_provider_state(
            installation_id=installation_id,
            provider="fake",
            expected_revision=1,
            state=ProviderConfigurationState.ENABLED,
        )

    assert captured.value.code is BankingAdministrationErrorCode.FEATURE_DISABLED
    assert store.calls == []


def test_registered_provider_can_be_enabled_when_feature_is_enabled() -> None:
    installation_id = uuid4()
    expected = configuration_record(
        installation_id=installation_id,
        state=ProviderConfigurationState.ENABLED,
        revision=2,
    )
    store = StoreStub(expected)
    service = BankingAdministrationService(
        store,
        registered_registry(),
        feature_enabled=True,
    )

    actual = service.set_provider_state(
        installation_id=installation_id,
        provider="fake",
        expected_revision=1,
        state=ProviderConfigurationState.ENABLED,
    )

    assert actual is expected
    assert store.calls == [("state", "fake")]


def test_known_configuration_can_be_disabled_without_registered_adapter() -> None:
    installation_id = uuid4()
    expected = configuration_record(
        installation_id=installation_id,
        state=ProviderConfigurationState.DISABLED,
        revision=2,
    )
    store = StoreStub(expected)
    service = BankingAdministrationService(
        store,
        BankingProviderRegistry().freeze(),
        feature_enabled=False,
    )

    actual = service.set_provider_state(
        installation_id=installation_id,
        provider="fake",
        expected_revision=1,
        state=ProviderConfigurationState.DISABLED,
    )

    assert actual is expected
    assert store.calls == [("state", "fake")]


@pytest.mark.parametrize(
    ("persistence_error", "expected_code"),
    [
        (
            ConfigurationNotFoundError("unsafe-not-found-detail"),
            BankingAdministrationErrorCode.CONFIGURATION_NOT_FOUND,
        ),
        (
            ConfigurationConflictError("unsafe-conflict-detail"),
            BankingAdministrationErrorCode.CONFIGURATION_CONFLICT,
        ),
        (
            BankingPersistenceError("unsafe-driver-detail"),
            BankingAdministrationErrorCode.PERSISTENCE_FAILURE,
        ),
    ],
)
def test_persistence_errors_are_mapped_without_original_diagnostics(
    persistence_error: BankingPersistenceError,
    expected_code: BankingAdministrationErrorCode,
) -> None:
    installation_id = uuid4()
    store = StoreStub(configuration_record(installation_id=installation_id))
    store.error = persistence_error
    service = BankingAdministrationService(
        store,
        registered_registry(),
        feature_enabled=True,
    )

    with pytest.raises(BankingAdministrationError) as captured:
        service.get_provider_configuration(
            installation_id=installation_id,
            provider="fake",
        )

    assert captured.value.code is expected_code
    assert "unsafe" not in str(captured.value)
    assert captured.value.__cause__ is None
