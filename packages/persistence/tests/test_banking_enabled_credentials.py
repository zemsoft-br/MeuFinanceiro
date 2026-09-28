from __future__ import annotations

from dataclasses import fields
from uuid import UUID, uuid4

import pytest
from meufinanceiro_security.envelope import SecretCipher
from meufinanceiro_security.keyring import create_keyring
from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine

from meufinanceiro_persistence import (
    BankingIntegrationStore,
    BankingPersistenceError,
    ConfigurationNotFoundError,
    EnabledProviderCredentials,
    ProviderConfigurationRecord,
    ProviderConfigurationState,
    ProviderNotEnabledError,
)
from meufinanceiro_persistence.schema import provider_configurations


@pytest.fixture
def cipher() -> SecretCipher:
    return SecretCipher(create_keyring())


@pytest.fixture
def store(
    runtime_engine: Engine,
    cipher: SecretCipher,
) -> BankingIntegrationStore:
    return BankingIntegrationStore(runtime_engine, cipher)


def create_configuration(
    store: BankingIntegrationStore,
    *,
    installation_id: UUID,
    state: ProviderConfigurationState = ProviderConfigurationState.ENABLED,
) -> ProviderConfigurationRecord:
    configured = store.create_configuration(
        installation_id=installation_id,
        provider="pluggy",
        client_id="ephemeral-client-id",
        client_secret="ephemeral-client-secret",
    )
    if state is ProviderConfigurationState.CONFIGURED:
        return configured
    return store.set_configuration_state(
        installation_id=installation_id,
        provider="pluggy",
        expected_revision=configured.configuration_revision,
        state=state,
    )


def test_enabled_credentials_are_available_only_inside_callback(
    runtime_engine: Engine,
    store: BankingIntegrationStore,
) -> None:
    installation_id = uuid4()
    enabled = create_configuration(store, installation_id=installation_id)
    observed: dict[str, object] = {}

    def operation(credentials: EnabledProviderCredentials) -> tuple[str, int]:
        observed.update(
            provider=credentials.provider,
            configuration_id=credentials.configuration_id,
            revision=credentials.configuration_revision,
            client_id=credentials.client_id,
            client_secret=credentials.client_secret,
            rendered=repr(credentials),
        )
        with runtime_engine.connect() as connection:
            context = connection.scalar(
                select(func.current_setting("app.current_installation_id", True))
            )
        observed["transaction_context"] = context
        return credentials.provider, credentials.configuration_revision

    result = store.use_enabled_credentials(
        installation_id=installation_id,
        provider="pluggy",
        operation=operation,
    )

    assert result == ("pluggy", enabled.configuration_revision)
    assert observed["provider"] == "pluggy"
    assert observed["configuration_id"] == enabled.id
    assert observed["client_id"] == "ephemeral-client-id"
    assert observed["client_secret"] == "ephemeral-client-secret"
    assert observed["transaction_context"] in {None, ""}
    rendered = str(observed["rendered"])
    assert "ephemeral-client-id" not in rendered
    assert "ephemeral-client-secret" not in rendered
    assert "<redacted>" in rendered


def test_enabled_credentials_type_has_no_envelope_fields() -> None:
    names = {field.name for field in fields(EnabledProviderCredentials)}
    assert "client_id_envelope" not in names
    assert "client_secret_envelope" not in names


@pytest.mark.parametrize(
    "state",
    [ProviderConfigurationState.CONFIGURED, ProviderConfigurationState.DISABLED],
)
def test_non_enabled_configuration_fails_before_callback(
    store: BankingIntegrationStore,
    state: ProviderConfigurationState,
) -> None:
    installation_id = uuid4()
    create_configuration(store, installation_id=installation_id, state=state)
    called = False

    def operation(credentials: EnabledProviderCredentials) -> None:
        nonlocal called
        del credentials
        called = True

    with pytest.raises(ProviderNotEnabledError):
        store.use_enabled_credentials(
            installation_id=installation_id,
            provider="pluggy",
            operation=operation,
        )
    assert called is False


def test_missing_configuration_fails_before_callback(
    store: BankingIntegrationStore,
) -> None:
    called = False

    def operation(credentials: EnabledProviderCredentials) -> None:
        nonlocal called
        del credentials
        called = True

    with pytest.raises(ConfigurationNotFoundError):
        store.use_enabled_credentials(
            installation_id=uuid4(),
            provider="pluggy",
            operation=operation,
        )
    assert called is False


def test_swapped_envelopes_fail_aad_authentication_without_leak(
    engine: Engine,
    store: BankingIntegrationStore,
) -> None:
    installation_id = uuid4()
    enabled = create_configuration(store, installation_id=installation_id)
    with engine.begin() as connection:
        row = (
            connection.execute(
                select(
                    provider_configurations.c.client_id_envelope,
                    provider_configurations.c.client_secret_envelope,
                ).where(provider_configurations.c.id == enabled.id)
            )
            .mappings()
            .one()
        )
        connection.execute(
            update(provider_configurations)
            .where(provider_configurations.c.id == enabled.id)
            .values(
                client_id_envelope=row["client_secret_envelope"],
                client_secret_envelope=row["client_id_envelope"],
            )
        )

    with pytest.raises(BankingPersistenceError) as raised:
        store.use_enabled_credentials(
            installation_id=installation_id,
            provider="pluggy",
            operation=lambda credentials: credentials.provider,
        )
    assert str(raised.value) == "provider credentials could not be decrypted"
    assert raised.value.__cause__ is None
    assert "ephemeral" not in str(raised.value)


def test_tampered_envelope_is_sanitized(
    engine: Engine,
    store: BankingIntegrationStore,
) -> None:
    installation_id = uuid4()
    enabled = create_configuration(store, installation_id=installation_id)
    with engine.begin() as connection:
        connection.execute(
            update(provider_configurations)
            .where(provider_configurations.c.id == enabled.id)
            .values(client_secret_envelope="not-an-envelope")
        )

    with pytest.raises(BankingPersistenceError) as raised:
        store.use_enabled_credentials(
            installation_id=installation_id,
            provider="pluggy",
            operation=lambda credentials: credentials.provider,
        )
    assert str(raised.value) == "provider credentials could not be decrypted"
    assert raised.value.__cause__ is None


def test_unavailable_key_is_sanitized(
    runtime_engine: Engine,
    store: BankingIntegrationStore,
) -> None:
    installation_id = uuid4()
    create_configuration(store, installation_id=installation_id)
    store_with_other_key = BankingIntegrationStore(
        runtime_engine,
        SecretCipher(create_keyring()),
    )

    with pytest.raises(BankingPersistenceError) as raised:
        store_with_other_key.use_enabled_credentials(
            installation_id=installation_id,
            provider="pluggy",
            operation=lambda credentials: credentials.provider,
        )
    assert str(raised.value) == "provider credentials could not be decrypted"
    assert raised.value.__cause__ is None


def test_callback_exception_propagates_unchanged(
    store: BankingIntegrationStore,
) -> None:
    installation_id = uuid4()
    create_configuration(store, installation_id=installation_id)
    expected = LookupError("operation failed")

    def operation(credentials: EnabledProviderCredentials) -> None:
        assert credentials.client_id == "ephemeral-client-id"
        raise expected

    with pytest.raises(LookupError) as raised:
        store.use_enabled_credentials(
            installation_id=installation_id,
            provider="pluggy",
            operation=operation,
        )
    assert raised.value is expected


def test_invalid_provider_and_operation_are_rejected_without_database_access(
    store: BankingIntegrationStore,
) -> None:
    with pytest.raises(ValueError):
        store.use_enabled_credentials(
            installation_id=uuid4(),
            provider="Pluggy",
            operation=lambda credentials: credentials.provider,
        )
    with pytest.raises(TypeError):
        store.use_enabled_credentials(
            installation_id=uuid4(),
            provider="pluggy",
            operation=None,  # type: ignore[arg-type]
        )
