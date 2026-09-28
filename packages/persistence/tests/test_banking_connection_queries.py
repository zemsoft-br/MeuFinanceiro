from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields
from datetime import UTC, datetime
from uuid import UUID, uuid4

from meufinanceiro_security.envelope import SecretCipher
from meufinanceiro_security.keyring import create_keyring
from sqlalchemy.engine import Engine

from meufinanceiro_persistence import (
    BankingConnectionQueryStore,
    BankingIntegrationStore,
    LocalBankingConnectionRecord,
    ProviderConfigurationState,
    StoredConnectionStatus,
)

NOW = datetime(2026, 8, 8, tzinfo=UTC)


def _integration_store(runtime_engine: Engine) -> BankingIntegrationStore:
    return BankingIntegrationStore(runtime_engine, SecretCipher(create_keyring()))


def _enable_configuration(
    store: BankingIntegrationStore,
    installation_id: UUID,
) -> int:
    configured = store.create_configuration(
        installation_id=installation_id,
        provider="pluggy",
        client_id="synthetic-client-id",
        client_secret="synthetic-client-secret",
    )
    enabled = store.set_configuration_state(
        installation_id=installation_id,
        provider="pluggy",
        expected_revision=configured.configuration_revision,
        state=ProviderConfigurationState.ENABLED,
    )
    return enabled.configuration_revision


def test_query_lists_only_allowlisted_local_metadata_for_one_residence(
    runtime_engine: Engine,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_a = uuid4()
    residence_b = uuid4()
    create_canonical_residences(installation_id, (residence_a, residence_b))
    integration = _integration_store(runtime_engine)
    revision = _enable_configuration(integration, installation_id)

    first = integration.register_connection(
        installation_id=installation_id,
        residence_id=residence_a,
        provider="pluggy",
        external_connection_id="provider-item-a1",
        status=StoredConnectionStatus.REAUTHENTICATION_REQUIRED,
        requires_user_action=True,
        last_attempt_at=NOW,
    )
    second = integration.register_connection(
        installation_id=installation_id,
        residence_id=residence_a,
        provider="pluggy",
        external_connection_id="provider-item-a2",
        status=StoredConnectionStatus.DISCONNECTED,
        requires_user_action=False,
        disconnected_at=NOW,
    )
    integration.register_connection(
        installation_id=installation_id,
        residence_id=residence_b,
        provider="pluggy",
        external_connection_id="provider-item-b1",
        status=StoredConnectionStatus.AVAILABLE,
        requires_user_action=False,
    )
    integration.set_configuration_state(
        installation_id=installation_id,
        provider="pluggy",
        expected_revision=revision,
        state=ProviderConfigurationState.DISABLED,
    )

    query = BankingConnectionQueryStore(runtime_engine)
    records = query.list_connections(
        installation_id=installation_id,
        residence_id=residence_a,
    )

    assert {record.id for record in records} == {first.id, second.id}
    assert len(records) == 2
    assert any(
        record.status is StoredConnectionStatus.DISCONNECTED for record in records
    )
    assert all(record.provider == "pluggy" for record in records)
    assert "external_connection_id" not in {
        field.name for field in fields(LocalBankingConnectionRecord)
    }
    assert "provider_reason_code" not in {
        field.name for field in fields(LocalBankingConnectionRecord)
    }


def test_query_is_empty_for_residence_without_connections(
    runtime_engine: Engine,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    installation_id = uuid4()
    residence_a = uuid4()
    residence_b = uuid4()
    create_canonical_residences(installation_id, (residence_a, residence_b))
    integration = _integration_store(runtime_engine)
    _enable_configuration(integration, installation_id)
    integration.register_connection(
        installation_id=installation_id,
        residence_id=residence_a,
        provider="pluggy",
        external_connection_id="provider-item-a1",
        status=StoredConnectionStatus.AVAILABLE,
        requires_user_action=False,
    )

    records = BankingConnectionQueryStore(runtime_engine).list_connections(
        installation_id=installation_id,
        residence_id=residence_b,
    )

    assert records == ()
