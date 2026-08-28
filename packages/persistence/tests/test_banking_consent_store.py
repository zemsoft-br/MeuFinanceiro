from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from meufinanceiro_security.envelope import SecretCipher
from meufinanceiro_security.keyring import create_keyring
from sqlalchemy import select, update
from sqlalchemy.engine import Engine

from meufinanceiro_persistence import (
    BankingConsentConnectionStore,
    BankingIntegrationStore,
    ConnectionNotFoundError,
    ProviderConfigurationState,
    StoredConnectionStatus,
)
from meufinanceiro_persistence.schema import (
    household_memberships,
    identity_operators,
)

NOW = datetime(2026, 8, 28, 0, 0, tzinfo=UTC)


def _banking_store(runtime_engine: Engine) -> BankingIntegrationStore:
    return BankingIntegrationStore(runtime_engine, SecretCipher(create_keyring()))


def _enable_provider(
    store: BankingIntegrationStore,
    *,
    installation_id: UUID,
) -> None:
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


def _operator_id(engine: Engine, installation_id: UUID) -> UUID:
    with engine.begin() as connection:
        value = connection.scalar(
            select(identity_operators.c.id).where(
                identity_operators.c.installation_id == installation_id
            )
        )
    assert isinstance(value, UUID)
    return value


def _connection(
    *,
    engine: Engine,
    runtime_engine: Engine,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
    residence_ids: tuple[UUID, ...],
) -> tuple[UUID, UUID, UUID, UUID]:
    installation_id = uuid4()
    create_canonical_residences(installation_id, residence_ids)
    operator_id = _operator_id(engine, installation_id)
    store = _banking_store(runtime_engine)
    _enable_provider(store, installation_id=installation_id)
    record = store.register_connection(
        installation_id=installation_id,
        residence_id=residence_ids[0],
        provider="pluggy",
        external_connection_id="synthetic-external-item",
        status=StoredConnectionStatus.AVAILABLE,
        requires_user_action=False,
        consent_expires_at=NOW + timedelta(days=45),
    )
    return installation_id, residence_ids[0], operator_id, record.id


def test_consent_store_returns_only_actor_authorized_minimal_facts(
    engine: Engine,
    runtime_engine: Engine,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    residence_id = uuid4()
    installation_id, residence_id, operator_id, connection_id = _connection(
        engine=engine,
        runtime_engine=runtime_engine,
        create_canonical_residences=create_canonical_residences,
        residence_ids=(residence_id,),
    )

    snapshot = BankingConsentConnectionStore(
        runtime_engine
    ).get_consent_connection_snapshot(
        installation_id=installation_id,
        residence_id=residence_id,
        operator_id=operator_id,
        connection_id=connection_id,
    )

    assert snapshot.status is StoredConnectionStatus.AVAILABLE
    assert snapshot.consent_expires_at == NOW + timedelta(days=45)
    rendered = repr(snapshot)
    assert str(connection_id) not in rendered
    assert "pluggy" not in rendered.lower()
    assert "synthetic-external-item" not in rendered


def test_consent_store_fails_closed_for_cross_residence_connection(
    engine: Engine,
    runtime_engine: Engine,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    first_residence = uuid4()
    second_residence = uuid4()
    installation_id, _residence_id, operator_id, connection_id = _connection(
        engine=engine,
        runtime_engine=runtime_engine,
        create_canonical_residences=create_canonical_residences,
        residence_ids=(first_residence, second_residence),
    )

    with pytest.raises(ConnectionNotFoundError, match="banking connection was not found"):
        BankingConsentConnectionStore(
            runtime_engine
        ).get_consent_connection_snapshot(
            installation_id=installation_id,
            residence_id=second_residence,
            operator_id=operator_id,
            connection_id=connection_id,
        )


def test_consent_store_fails_closed_for_inactive_membership(
    engine: Engine,
    runtime_engine: Engine,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    residence_id = uuid4()
    installation_id, residence_id, operator_id, connection_id = _connection(
        engine=engine,
        runtime_engine=runtime_engine,
        create_canonical_residences=create_canonical_residences,
        residence_ids=(residence_id,),
    )
    with engine.begin() as connection:
        connection.execute(
            update(household_memberships)
            .where(
                household_memberships.c.installation_id == installation_id,
                household_memberships.c.residence_id == residence_id,
                household_memberships.c.operator_id == operator_id,
            )
            .values(status="disabled", is_primary=False)
        )

    with pytest.raises(ConnectionNotFoundError, match="banking connection was not found"):
        BankingConsentConnectionStore(
            runtime_engine
        ).get_consent_connection_snapshot(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            connection_id=connection_id,
        )


def test_consent_store_fails_closed_for_unknown_operator(
    engine: Engine,
    runtime_engine: Engine,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    residence_id = uuid4()
    installation_id, residence_id, _operator_id_value, connection_id = _connection(
        engine=engine,
        runtime_engine=runtime_engine,
        create_canonical_residences=create_canonical_residences,
        residence_ids=(residence_id,),
    )

    with pytest.raises(ConnectionNotFoundError, match="banking connection was not found"):
        BankingConsentConnectionStore(
            runtime_engine
        ).get_consent_connection_snapshot(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=uuid4(),
            connection_id=connection_id,
        )
