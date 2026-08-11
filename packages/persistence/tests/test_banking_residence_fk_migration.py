from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.engine import Connection, Engine

from meufinanceiro_persistence.migrations import (
    build_alembic_config,
    current_revision,
)
from meufinanceiro_persistence.schema import (
    connections,
    household_residences,
    provider_configurations,
)

_CONSTRAINT_NAME = "fk_connections_household_residence_scope"
_PREVIOUS_REVISION = "0005_household_residences"
_HEAD_REVISION = "0006_banking_residence_fk"
_ERROR_MESSAGE = "banking connections contain non-canonical residence references"
NOW = datetime(2026, 8, 7, 0, 0, tzinfo=UTC)


def _insert_configuration(connection: Connection, installation_id: UUID) -> UUID:
    configuration_id = uuid4()
    connection.execute(
        insert(provider_configurations).values(
            id=configuration_id,
            installation_id=installation_id,
            provider="pluggy",
            state="disabled",
            client_id_envelope=None,
            client_secret_envelope=None,
            configuration_revision=1,
            created_at=NOW,
            updated_at=NOW,
            enabled_at=None,
            disabled_at=NOW,
        )
    )
    return configuration_id


def _insert_connection(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    configuration_id: UUID,
    external_id: str,
) -> UUID:
    connection_id = uuid4()
    connection.execute(
        insert(connections).values(
            id=connection_id,
            installation_id=installation_id,
            residence_id=residence_id,
            provider="pluggy",
            provider_configuration_id=configuration_id,
            external_connection_id=external_id,
            status="AVAILABLE",
            requires_user_action=False,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    return connection_id


def _constraint_delete_action(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return connection.scalar(
            text(
                """
                SELECT confdeltype::text
                FROM pg_constraint
                WHERE conname = :constraint_name
                  AND conrelid = 'integrations.connections'::regclass
                """
            ),
            {"constraint_name": _CONSTRAINT_NAME},
        )


def _assert_upgrade_rejected(
    config: Config,
    engine: Engine,
    *,
    external_id: str,
    residence_id: UUID,
) -> None:
    with pytest.raises(RuntimeError) as captured:
        command.upgrade(config, "head")

    assert current_revision(engine) == _PREVIOUS_REVISION
    assert str(captured.value) == _ERROR_MESSAGE
    assert external_id not in str(captured.value)
    assert str(residence_id) not in str(captured.value)
    assert _constraint_delete_action(engine) is None


def _clean_banking_rows(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(delete(connections))
        connection.execute(delete(provider_configurations))


def test_banking_residence_fk_migration_fails_closed_and_roundtrips(
    database_url: str,
    app_database_user: str,
    engine: Engine,
    create_canonical_residences: Callable[[UUID, tuple[UUID, ...]], None],
) -> None:
    config = build_alembic_config(
        database_url,
        app_database_user=app_database_user,
    )
    command.downgrade(config, _PREVIOUS_REVISION)
    assert current_revision(engine) == _PREVIOUS_REVISION
    assert _constraint_delete_action(engine) is None

    try:
        missing_installation_id = uuid4()
        missing_residence_id = uuid4()
        missing_external_id = "missing-residence-migration-sentinel"
        with engine.begin() as connection:
            configuration_id = _insert_configuration(
                connection,
                missing_installation_id,
            )
            _insert_connection(
                connection,
                installation_id=missing_installation_id,
                residence_id=missing_residence_id,
                configuration_id=configuration_id,
                external_id=missing_external_id,
            )
        _assert_upgrade_rejected(
            config,
            engine,
            external_id=missing_external_id,
            residence_id=missing_residence_id,
        )
        _clean_banking_rows(engine)

        installation_id = uuid4()
        residence_id = uuid4()
        create_canonical_residences(installation_id, (residence_id,))

        cross_installation_id = uuid4()
        cross_external_id = "cross-installation-migration-sentinel"
        with engine.begin() as connection:
            configuration_id = _insert_configuration(
                connection,
                cross_installation_id,
            )
            _insert_connection(
                connection,
                installation_id=cross_installation_id,
                residence_id=residence_id,
                configuration_id=configuration_id,
                external_id=cross_external_id,
            )
        _assert_upgrade_rejected(
            config,
            engine,
            external_id=cross_external_id,
            residence_id=residence_id,
        )
        _clean_banking_rows(engine)

        with engine.begin() as connection:
            configuration_id = _insert_configuration(connection, installation_id)
            connection_id = _insert_connection(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
                configuration_id=configuration_id,
                external_id="canonical-migration-sentinel",
            )

        command.upgrade(config, "head")
        assert current_revision(engine) == _HEAD_REVISION
        assert _constraint_delete_action(engine) == "r"

        with engine.connect() as connection:
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(connections)
                    .where(connections.c.id == connection_id)
                )
                == 1
            )
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(household_residences)
                    .where(
                        household_residences.c.id == residence_id,
                        household_residences.c.installation_id == installation_id,
                    )
                )
                == 1
            )

        command.downgrade(config, _PREVIOUS_REVISION)
        assert current_revision(engine) == _PREVIOUS_REVISION
        assert _constraint_delete_action(engine) is None
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(connections)
                    .where(connections.c.id == connection_id)
                )
                == 1
            )
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(household_residences)
                    .where(household_residences.c.id == residence_id)
                )
                == 1
            )
    finally:
        _clean_banking_rows(engine)
        command.upgrade(config, "head")
        assert current_revision(engine) == _HEAD_REVISION
