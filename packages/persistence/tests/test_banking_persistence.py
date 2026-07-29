from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from meufinanceiro_security.envelope import Envelope, SecretCipher
from meufinanceiro_security.errors import EnvelopeIntegrityError
from meufinanceiro_security.keyring import create_keyring
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.banking import (
    BankingIntegrationStore,
    CapabilitySnapshot,
    ConfigurationConflictError,
    ProviderConfigurationRecord,
    ProviderConfigurationState,
    StoredCapability,
    StoredCapabilitySource,
    StoredCapabilityState,
    StoredConnectionStatus,
    credential_aad,
)
from meufinanceiro_persistence.schema import (
    connection_capabilities,
    connections,
    provider_configurations,
)

NOW = datetime(2026, 7, 28, 16, 0, tzinfo=UTC)


@pytest.fixture
def cipher() -> SecretCipher:
    return SecretCipher(create_keyring())


@pytest.fixture
def store(runtime_engine: Engine, cipher: SecretCipher) -> BankingIntegrationStore:
    return BankingIntegrationStore(runtime_engine, cipher)


def _enable_configuration(
    store: BankingIntegrationStore,
    *,
    installation_id: UUID,
    provider: str = "pluggy",
) -> ProviderConfigurationRecord:
    configured = store.create_configuration(
        installation_id=installation_id,
        provider=provider,
        client_id="synthetic-client-id",
        client_secret="synthetic-client-secret",
    )
    return store.set_configuration_state(
        installation_id=installation_id,
        provider=provider,
        expected_revision=configured.configuration_revision,
        state=ProviderConfigurationState.ENABLED,
    )


def _set_context(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID | None = None,
) -> None:
    connection.execute(
        select(
            func.set_config(
                "app.current_installation_id",
                str(installation_id),
                True,
            )
        )
    )
    if residence_id is not None:
        connection.execute(
            select(
                func.set_config(
                    "app.current_residence_id",
                    str(residence_id),
                    True,
                )
            )
        )


def test_configuration_encrypts_credentials_and_hides_envelopes(
    engine: Engine,
    store: BankingIntegrationStore,
    cipher: SecretCipher,
) -> None:
    installation_id = uuid4()
    record = store.create_configuration(
        installation_id=installation_id,
        provider="pluggy",
        client_id="client-id-value",
        client_secret="client-secret-value",
    )

    assert record.state is ProviderConfigurationState.CONFIGURED
    assert record.configuration_revision == 1
    assert "client_id_envelope" not in {field.name for field in fields(record)}
    assert "client_secret_envelope" not in {field.name for field in fields(record)}

    with engine.connect() as connection:
        row = (
            connection.execute(
                select(
                    provider_configurations.c.client_id_envelope,
                    provider_configurations.c.client_secret_envelope,
                ).where(provider_configurations.c.id == record.id)
            )
            .mappings()
            .one()
        )

    client_id_envelope = row["client_id_envelope"]
    client_secret_envelope = row["client_secret_envelope"]
    assert "client-id-value" not in client_id_envelope
    assert "client-secret-value" not in client_secret_envelope
    assert Envelope.parse(client_id_envelope).key_id == cipher.active_key_id
    assert (
        cipher.decrypt_text(
            client_id_envelope,
            aad=credential_aad(
                installation_id,
                "pluggy",
                record.id,
                "client_id",
            ),
        )
        == "client-id-value"
    )
    assert (
        cipher.decrypt_text(
            client_secret_envelope,
            aad=credential_aad(
                installation_id,
                "pluggy",
                record.id,
                "client_secret",
            ),
        )
        == "client-secret-value"
    )
    with pytest.raises(EnvelopeIntegrityError):
        cipher.decrypt_text(
            client_secret_envelope,
            aad=credential_aad(
                uuid4(),
                "pluggy",
                record.id,
                "client_secret",
            ),
        )


def test_configuration_compare_and_swap_and_credential_replacement(
    engine: Engine,
    store: BankingIntegrationStore,
    cipher: SecretCipher,
) -> None:
    installation_id = uuid4()
    configured = store.create_configuration(
        installation_id=installation_id,
        provider="pluggy",
        client_id="first-client",
        client_secret="first-secret",
    )
    enabled = store.set_configuration_state(
        installation_id=installation_id,
        provider="pluggy",
        expected_revision=1,
        state=ProviderConfigurationState.ENABLED,
    )

    assert enabled.configuration_revision == 2
    assert enabled.enabled_at is not None
    with pytest.raises(ConfigurationConflictError, match="revision changed"):
        store.set_configuration_state(
            installation_id=installation_id,
            provider="pluggy",
            expected_revision=1,
            state=ProviderConfigurationState.DISABLED,
        )

    replaced = store.replace_credentials(
        installation_id=installation_id,
        provider="pluggy",
        expected_revision=2,
        client_id="second-client",
        client_secret="second-secret",
    )
    assert replaced.configuration_revision == 3
    assert replaced.state is ProviderConfigurationState.ENABLED

    with engine.connect() as connection:
        envelope = connection.scalar(
            select(provider_configurations.c.client_secret_envelope).where(
                provider_configurations.c.id == configured.id
            )
        )
    assert envelope is not None
    assert (
        cipher.decrypt_text(
            envelope,
            aad=credential_aad(
                installation_id,
                "pluggy",
                configured.id,
                "client_secret",
            ),
        )
        == "second-secret"
    )


def test_connection_reuse_and_capability_snapshot_are_idempotent(
    store: BankingIntegrationStore,
) -> None:
    installation_id = uuid4()
    residence_id = uuid4()
    _enable_configuration(store, installation_id=installation_id)

    created = store.register_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        provider="pluggy",
        external_connection_id="external-item-1",
        status=StoredConnectionStatus.AVAILABLE,
        requires_user_action=False,
        last_attempt_at=NOW,
    )
    reused = store.register_connection(
        installation_id=installation_id,
        residence_id=residence_id,
        provider="pluggy",
        external_connection_id="external-item-1",
        status=StoredConnectionStatus.PARTIAL,
        requires_user_action=False,
        last_attempt_at=NOW + timedelta(minutes=1),
        provider_reason_code="PARTIAL_DATA",
    )

    assert reused.id == created.id
    assert reused.status is StoredConnectionStatus.PARTIAL

    first = store.replace_capabilities(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=created.id,
        snapshots=(
            CapabilitySnapshot(
                capability=StoredCapability.TRANSACTIONS,
                state=StoredCapabilityState.SUPPORTED,
                source=StoredCapabilitySource.OBSERVATION,
                observed_at=NOW,
            ),
            CapabilitySnapshot(
                capability=StoredCapability.INVESTMENTS,
                state=StoredCapabilityState.NOT_OBSERVED,
                source=StoredCapabilitySource.OBSERVATION,
                observed_at=NOW,
            ),
        ),
    )
    second = store.replace_capabilities(
        installation_id=installation_id,
        residence_id=residence_id,
        connection_id=created.id,
        snapshots=(
            CapabilitySnapshot(
                capability=StoredCapability.TRANSACTIONS,
                state=StoredCapabilityState.REQUIRES_USER_ACTION,
                source=StoredCapabilitySource.OPERATION,
                observed_at=NOW + timedelta(minutes=2),
                provider_reason_code="REAUTH_REQUIRED",
            ),
        ),
    )

    assert len(first) == 2
    assert len(second) == 1
    assert second[0].capability is StoredCapability.TRANSACTIONS
    assert second[0].state is StoredCapabilityState.REQUIRES_USER_ACTION


def test_rls_is_fail_closed_and_isolates_installations_and_residences(
    runtime_engine: Engine,
    store: BankingIntegrationStore,
) -> None:
    installation_a = uuid4()
    installation_b = uuid4()
    residence_a = uuid4()
    residence_b = uuid4()
    configuration_a = _enable_configuration(
        store,
        installation_id=installation_a,
    )
    _enable_configuration(store, installation_id=installation_b)

    connection_a = store.register_connection(
        installation_id=installation_a,
        residence_id=residence_a,
        provider="pluggy",
        external_connection_id="connection-a",
        status=StoredConnectionStatus.AVAILABLE,
        requires_user_action=False,
    )
    connection_b = store.register_connection(
        installation_id=installation_b,
        residence_id=residence_b,
        provider="pluggy",
        external_connection_id="connection-b",
        status=StoredConnectionStatus.AVAILABLE,
        requires_user_action=False,
    )
    store.replace_capabilities(
        installation_id=installation_a,
        residence_id=residence_a,
        connection_id=connection_a.id,
        snapshots=(
            CapabilitySnapshot(
                capability=StoredCapability.TRANSACTIONS,
                state=StoredCapabilityState.SUPPORTED,
                source=StoredCapabilitySource.OBSERVATION,
                observed_at=NOW,
            ),
        ),
    )
    store.replace_capabilities(
        installation_id=installation_b,
        residence_id=residence_b,
        connection_id=connection_b.id,
        snapshots=(
            CapabilitySnapshot(
                capability=StoredCapability.LOANS,
                state=StoredCapabilityState.SUPPORTED,
                source=StoredCapabilitySource.OBSERVATION,
                observed_at=NOW,
            ),
        ),
    )

    with runtime_engine.begin() as connection:
        assert (
            connection.scalar(select(func.count()).select_from(provider_configurations))
            == 0
        )
        assert connection.scalar(select(func.count()).select_from(connections)) == 0
        assert (
            connection.scalar(select(func.count()).select_from(connection_capabilities))
            == 0
        )

    with runtime_engine.begin() as connection:
        _set_context(
            connection,
            installation_id=installation_a,
            residence_id=residence_a,
        )
        assert (
            connection.scalar(select(func.count()).select_from(provider_configurations))
            == 1
        )
        assert connection.scalar(select(func.count()).select_from(connections)) == 1
        assert (
            connection.scalar(select(func.count()).select_from(connection_capabilities))
            == 1
        )
        assert (
            connection.execute(
                update(connections)
                .where(connections.c.id == connection_b.id)
                .values(status=StoredConnectionStatus.FAILED.value)
            ).rowcount
            == 0
        )
        assert (
            connection.execute(
                delete(connection_capabilities).where(
                    connection_capabilities.c.connection_id == connection_b.id
                )
            ).rowcount
            == 0
        )

    with pytest.raises(DBAPIError):
        with runtime_engine.begin() as connection:
            _set_context(
                connection,
                installation_id=installation_a,
                residence_id=residence_a,
            )
            connection.execute(
                insert(connections).values(
                    id=uuid4(),
                    installation_id=installation_a,
                    residence_id=residence_b,
                    provider="pluggy",
                    provider_configuration_id=configuration_a.id,
                    external_connection_id="blocked-cross-residence",
                    status=StoredConnectionStatus.AVAILABLE.value,
                    requires_user_action=False,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )


def test_composite_constraints_reject_cross_scope_associations(
    engine: Engine,
    store: BankingIntegrationStore,
) -> None:
    installation_a = uuid4()
    installation_b = uuid4()
    residence_a = uuid4()
    residence_b = uuid4()
    _enable_configuration(store, installation_id=installation_a)
    _enable_configuration(store, installation_id=installation_b)
    connection_a = store.register_connection(
        installation_id=installation_a,
        residence_id=residence_a,
        provider="pluggy",
        external_connection_id="scope-a",
        status=StoredConnectionStatus.AVAILABLE,
        requires_user_action=False,
    )

    with engine.connect() as connection:
        configuration_a = connection.scalar(
            select(provider_configurations.c.id).where(
                provider_configurations.c.installation_id == installation_a
            )
        )
    assert configuration_a is not None

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                insert(connections).values(
                    id=uuid4(),
                    installation_id=installation_b,
                    residence_id=residence_b,
                    provider="pluggy",
                    provider_configuration_id=configuration_a,
                    external_connection_id="cross-installation",
                    status=StoredConnectionStatus.AVAILABLE.value,
                    requires_user_action=False,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                insert(connection_capabilities).values(
                    id=uuid4(),
                    residence_id=residence_b,
                    connection_id=connection_a.id,
                    capability=StoredCapability.TRANSACTIONS.value,
                    state=StoredCapabilityState.SUPPORTED.value,
                    source=StoredCapabilitySource.OBSERVATION.value,
                    observed_at=NOW,
                    updated_at=NOW,
                )
            )


def test_runtime_role_has_no_rls_bypass_or_administrative_privileges(
    engine: Engine,
    app_database_user: str,
) -> None:
    with engine.connect() as connection:
        privileges = (
            connection.exec_driver_sql(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, "
                "rolreplication, rolbypassrls "
                "FROM pg_roles WHERE rolname = %s",
                (app_database_user,),
            )
            .mappings()
            .one()
        )

    assert dict(privileges) == {
        "rolsuper": False,
        "rolcreatedb": False,
        "rolcreaterole": False,
        "rolreplication": False,
        "rolbypassrls": False,
    }
