from __future__ import annotations

from uuid import uuid4

import pytest
from meufinanceiro_security.envelope import SecretCipher
from meufinanceiro_security.keyring import create_keyring
from sqlalchemy.engine import Engine

from meufinanceiro_persistence import (
    BankingIntegrationStore,
    ConnectionConflictError,
    ProviderConfigurationState,
    StoredConnectionStatus,
)


def test_cross_residence_conflict_never_echoes_external_identifier(
    runtime_engine: Engine,
) -> None:
    store = BankingIntegrationStore(
        runtime_engine,
        SecretCipher(create_keyring()),
    )
    installation_id = uuid4()
    residence_a = uuid4()
    residence_b = uuid4()
    external_id = "sensitive-external-connection-id"

    configured = store.create_configuration(
        installation_id=installation_id,
        provider="pluggy",
        client_id="synthetic-client-id",
        client_secret="synthetic-client-secret",
    )
    store.set_configuration_state(
        installation_id=installation_id,
        provider="pluggy",
        expected_revision=configured.configuration_revision,
        state=ProviderConfigurationState.ENABLED,
    )
    store.register_connection(
        installation_id=installation_id,
        residence_id=residence_a,
        provider="pluggy",
        external_connection_id=external_id,
        status=StoredConnectionStatus.AVAILABLE,
        requires_user_action=False,
    )

    with pytest.raises(ConnectionConflictError) as captured:
        store.register_connection(
            installation_id=installation_id,
            residence_id=residence_b,
            provider="pluggy",
            external_connection_id=external_id,
            status=StoredConnectionStatus.AVAILABLE,
            requires_user_action=False,
        )

    assert str(captured.value) == "external connection is already assigned"
    assert external_id not in str(captured.value)
    assert captured.value.__cause__ is None
