from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence import (
    IdentityBootstrapConflictError,
    MembershipRole,
    OperatorIdentityStore,
    OperatorRole,
    OperatorStatus,
)
from meufinanceiro_persistence.schema import (
    household_memberships,
    household_residences,
    identity_installation,
    identity_operators,
    identity_sessions,
)

NOW = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)
PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$test$not-a-real-hash-value"


@pytest.fixture(autouse=True)
def clean_identity(engine: Engine) -> Iterator[None]:
    with engine.begin() as connection:
        connection.execute(delete(identity_sessions))
        connection.execute(delete(household_memberships))
        connection.execute(delete(household_residences))
        connection.execute(delete(identity_operators))
        connection.execute(delete(identity_installation))
    yield
    with engine.begin() as connection:
        connection.execute(delete(identity_sessions))
        connection.execute(delete(household_memberships))
        connection.execute(delete(household_residences))
        connection.execute(delete(identity_operators))
        connection.execute(delete(identity_installation))


def test_bootstrap_creates_admin_primary_residence_and_owner_membership(
    runtime_engine: Engine,
    engine: Engine,
) -> None:
    store = OperatorIdentityStore(runtime_engine)

    record = store.bootstrap_installation_admin(
        login_name="  Admin.Local  ",
        password_hash=PASSWORD_HASH,
        residence_name="  Residência   Ipê  ",
    )

    assert record.login_name == "admin.local"
    assert record.role is OperatorRole.INSTALLATION_ADMIN
    assert record.status is OperatorStatus.ACTIVE
    assert record.primary_residence_id is not None
    assert record.primary_residence_name == "Residência Ipê"

    with engine.connect() as connection:
        residence = connection.execute(select(household_residences)).mappings().one()
        membership = connection.execute(select(household_memberships)).mappings().one()
    assert residence["id"] == record.primary_residence_id
    assert residence["installation_id"] == record.installation_id
    assert membership["operator_id"] == record.operator_id
    assert membership["residence_id"] == record.primary_residence_id
    assert membership["role"] == MembershipRole.OWNER.value
    assert membership["is_primary"] is True

    with pytest.raises(IdentityBootstrapConflictError):
        store.bootstrap_installation_admin(
            login_name="second-admin",
            password_hash=PASSWORD_HASH,
        )


def test_ensure_primary_residence_repairs_legacy_identity_idempotently(
    runtime_engine: Engine,
    engine: Engine,
) -> None:
    installation_id = uuid4()
    operator_id = uuid4()
    with engine.begin() as connection:
        created_at = connection.execute(select(func.transaction_timestamp())).scalar_one()
        connection.execute(
            identity_installation.insert().values(
                singleton=True,
                id=installation_id,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        connection.execute(
            identity_operators.insert().values(
                id=operator_id,
                installation_id=installation_id,
                login_name="legacy-admin",
                password_hash=PASSWORD_HASH,
                role=OperatorRole.INSTALLATION_ADMIN.value,
                status=OperatorStatus.ACTIVE.value,
                failed_attempts=0,
                locked_until=None,
                last_authenticated_at=None,
                password_changed_at=created_at,
                created_at=created_at,
                updated_at=created_at,
            )
        )

    store = OperatorIdentityStore(runtime_engine)
    first = store.ensure_primary_residence(residence_name="Casa antiga")
    second = store.ensure_primary_residence(residence_name="Nome ignorado")

    assert first == second
    assert first.installation_id == installation_id
    assert first.operator_id == operator_id
    assert first.residence_name == "Casa antiga"
    with engine.connect() as connection:
        assert connection.execute(
            select(func.count()).select_from(household_residences)
        ).scalar_one() == 1
        assert connection.execute(
            select(func.count()).select_from(household_memberships)
        ).scalar_one() == 1


def test_only_one_active_primary_membership_is_allowed(
    runtime_engine: Engine,
    engine: Engine,
) -> None:
    store = OperatorIdentityStore(runtime_engine)
    record = store.bootstrap_installation_admin(
        login_name="admin",
        password_hash=PASSWORD_HASH,
    )
    with engine.connect() as connection:
        existing = connection.execute(select(household_memberships)).mappings().one()
    second_residence_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            household_residences.insert().values(
                id=second_residence_id,
                installation_id=record.installation_id,
                name="Segunda residência",
                status="active",
                created_at=NOW,
                updated_at=NOW,
            )
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                household_memberships.insert().values(
                    id=uuid4(),
                    installation_id=record.installation_id,
                    residence_id=second_residence_id,
                    operator_id=record.operator_id,
                    role="owner",
                    status="active",
                    is_primary=True,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
    assert existing["is_primary"] is True


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


def test_session_contains_primary_residence_and_persists_only_token_hash(
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
    raw_token = "A" * 43
    token_hash = hashlib.sha256(raw_token.encode("ascii")).hexdigest()

    principal = store.create_session(
        material=material,
        token_hash=token_hash,
        authenticated_at=NOW,
        expires_at=NOW + timedelta(hours=8),
    )

    assert principal.primary_residence_id == record.primary_residence_id
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


def test_session_without_membership_has_no_fabricated_residence(
    runtime_engine: Engine,
    engine: Engine,
) -> None:
    installation_id = uuid4()
    operator_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            identity_installation.insert().values(
                singleton=True,
                id=installation_id,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            identity_operators.insert().values(
                id=operator_id,
                installation_id=installation_id,
                login_name="legacy-admin",
                password_hash=PASSWORD_HASH,
                role=OperatorRole.INSTALLATION_ADMIN.value,
                status=OperatorStatus.ACTIVE.value,
                failed_attempts=0,
                locked_until=None,
                last_authenticated_at=None,
                password_changed_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    store = OperatorIdentityStore(runtime_engine)
    material = store.get_authentication_material(login_name="legacy-admin")
    assert material is not None
    token_hash = hashlib.sha256(b"L" * 43).hexdigest()

    principal = store.create_session(
        material=material,
        token_hash=token_hash,
        authenticated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    assert principal.primary_residence_id is None
    assert store.resolve_session(token_hash=token_hash, observed_at=NOW) == principal


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


def test_runtime_role_has_no_delete_privilege_on_identity_or_household(
    runtime_engine: Engine,
) -> None:
    store = OperatorIdentityStore(runtime_engine)
    store.bootstrap_installation_admin(
        login_name="admin",
        password_hash=PASSWORD_HASH,
    )
    for table in (household_memberships, household_residences, identity_installation):
        with pytest.raises(DBAPIError):
            with runtime_engine.begin() as connection:
                connection.execute(table.delete())
