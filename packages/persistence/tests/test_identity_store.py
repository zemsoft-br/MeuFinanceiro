from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence import (
    IdentityBootstrapConflictError,
    OperatorIdentityStore,
    OperatorRole,
    OperatorStatus,
)
from meufinanceiro_persistence.schema import (
    identity_installation,
    identity_operators,
    identity_sessions,
)

NOW = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)
PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$test$not-a-real-hash-value"


def test_bootstrap_creates_single_installation_admin(
    runtime_engine: Engine,
) -> None:
    store = OperatorIdentityStore(runtime_engine)

    record = store.bootstrap_installation_admin(
        login_name="  Admin.Local  ",
        password_hash=PASSWORD_HASH,
    )

    assert record.login_name == "admin.local"
    assert record.role is OperatorRole.INSTALLATION_ADMIN
    assert record.status is OperatorStatus.ACTIVE

    with pytest.raises(IdentityBootstrapConflictError):
        store.bootstrap_installation_admin(
            login_name="second-admin",
            password_hash=PASSWORD_HASH,
        )


def test_authentication_material_redacts_password_hash(
    runtime_engine: Engine,
) -> None:
    store = OperatorIdentityStore(runtime_engine)
    store.bootstrap_installation_admin(
        login_name="admin",
        password_hash=PASSWORD_HASH,
    )

    material = store.get_authentication_material(login_name="admin")

    assert material is not None
    assert material.password_hash == PASSWORD_HASH
    assert PASSWORD_HASH not in repr(material)
    assert store.get_authentication_material(login_name="missing") is None


def test_failed_authentication_locks_at_threshold(
    runtime_engine: Engine,
) -> None:
    store = OperatorIdentityStore(runtime_engine)
    record = store.bootstrap_installation_admin(
        login_name="admin",
        password_hash=PASSWORD_HASH,
    )
    locked_until = NOW + timedelta(minutes=15)

    for _ in range(5):
        store.record_failed_authentication(
            operator_id=record.operator_id,
            lock_threshold=5,
            locked_until=locked_until,
        )

    material = store.get_authentication_material(login_name="admin")
    assert material is not None
    assert material.failed_attempts == 5
    assert material.locked_until == locked_until


def test_session_persists_only_token_hash_and_can_be_revoked(
    runtime_engine: Engine,
    engine: Engine,
) -> None:
    store = OperatorIdentityStore(runtime_engine)
    store.bootstrap_installation_admin(
        login_name="admin",
        password_hash=PASSWORD_HASH,
    )
    material = store.get_authentication_material(login_name="admin")
    assert material is not None
    raw_token = "A" * 43
    token_hash = hashlib.sha256(raw_token.encode("ascii")).hexdigest()

    principal = store.create_session(
        material=material,
        token_hash=token_hash,
        authenticated_at=NOW,
        expires_at=NOW + timedelta(hours=8),
    )

    with engine.connect() as connection:
        row = connection.execute(select(identity_sessions)).mappings().one()
    assert row["token_hash"] == token_hash
    assert raw_token not in str(dict(row))
    assert store.resolve_session(token_hash=token_hash, observed_at=NOW) == principal

    store.revoke_session(token_hash=token_hash, revoked_at=NOW + timedelta(minutes=1))
    assert (
        store.resolve_session(
            token_hash=token_hash,
            observed_at=NOW + timedelta(minutes=2),
        )
        is None
    )


def test_expired_session_and_disabled_operator_are_rejected(
    runtime_engine: Engine,
    engine: Engine,
) -> None:
    store = OperatorIdentityStore(runtime_engine)
    record = store.bootstrap_installation_admin(
        login_name="admin",
        password_hash=PASSWORD_HASH,
    )
    material = store.get_authentication_material(login_name="admin")
    assert material is not None
    first_hash = hashlib.sha256(b"B" * 43).hexdigest()
    store.create_session(
        material=material,
        token_hash=first_hash,
        authenticated_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
    )
    assert (
        store.resolve_session(
            token_hash=first_hash,
            observed_at=NOW + timedelta(minutes=2),
        )
        is None
    )

    second_hash = hashlib.sha256(b"C" * 43).hexdigest()
    store.create_session(
        material=material,
        token_hash=second_hash,
        authenticated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    with engine.begin() as connection:
        connection.execute(
            update(identity_operators)
            .where(identity_operators.c.id == record.operator_id)
            .values(status=OperatorStatus.DISABLED.value)
        )
    assert store.resolve_session(token_hash=second_hash, observed_at=NOW) is None


def test_runtime_role_has_no_delete_privilege(
    runtime_engine: Engine,
) -> None:
    store = OperatorIdentityStore(runtime_engine)
    store.bootstrap_installation_admin(
        login_name="admin",
        password_hash=PASSWORD_HASH,
    )
    with pytest.raises(DBAPIError):
        with runtime_engine.begin() as connection:
            connection.execute(identity_installation.delete())
