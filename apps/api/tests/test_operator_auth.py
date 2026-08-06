from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from meufinanceiro_persistence import (
    OperatorAuthenticationMaterial,
    OperatorRole,
    OperatorSessionPrincipal,
    OperatorStatus,
)
from meufinanceiro_security.passwords import PasswordService

from app.services.operator_auth import (
    InvalidOperatorCredentialsError,
    InvalidOperatorSessionError,
    LOCK_DURATION,
    LOCK_THRESHOLD,
    OperatorAuthenticationService,
)

NOW = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)
INSTALLATION_ID = uuid4()
OPERATOR_ID = uuid4()
SESSION_ID = uuid4()
PASSWORD = "correct horse battery staple"
TOKEN = "T" * 43


class StoreStub:
    def __init__(self, material: OperatorAuthenticationMaterial | None) -> None:
        self.material = material
        self.failed_calls: list[tuple[UUID, int, datetime]] = []
        self.created_hash: str | None = None
        self.resolved: OperatorSessionPrincipal | None = None
        self.revoked_hash: str | None = None

    def get_authentication_material(
        self, *, login_name: str
    ) -> OperatorAuthenticationMaterial | None:
        del login_name
        return self.material

    def record_failed_authentication(
        self,
        *,
        operator_id: UUID,
        lock_threshold: int,
        locked_until: datetime,
    ) -> None:
        self.failed_calls.append((operator_id, lock_threshold, locked_until))

    def create_session(
        self,
        *,
        material: OperatorAuthenticationMaterial,
        token_hash: str,
        expires_at: datetime,
        authenticated_at: datetime,
    ) -> OperatorSessionPrincipal:
        del authenticated_at
        self.created_hash = token_hash
        self.resolved = OperatorSessionPrincipal(
            session_id=SESSION_ID,
            installation_id=material.installation_id,
            operator_id=material.operator_id,
            login_name=material.login_name,
            role=material.role,
            expires_at=expires_at,
        )
        return self.resolved

    def resolve_session(
        self,
        *,
        token_hash: str,
        observed_at: datetime,
    ) -> OperatorSessionPrincipal | None:
        del token_hash, observed_at
        return self.resolved

    def revoke_session(self, *, token_hash: str, revoked_at: datetime) -> None:
        del revoked_at
        self.revoked_hash = token_hash


def material() -> OperatorAuthenticationMaterial:
    return OperatorAuthenticationMaterial(
        installation_id=INSTALLATION_ID,
        operator_id=OPERATOR_ID,
        login_name="admin",
        password_hash=PasswordService().hash(PASSWORD),
        role=OperatorRole.INSTALLATION_ADMIN,
        status=OperatorStatus.ACTIVE,
        failed_attempts=0,
        locked_until=None,
    )


def service(store: StoreStub) -> OperatorAuthenticationService:
    return OperatorAuthenticationService(
        store,
        clock=lambda: NOW,
        token_factory=lambda: TOKEN,
    )


def test_login_issues_opaque_session_and_redacts_token() -> None:
    store = StoreStub(material())

    issued = service(store).login(login_name=" ADMIN ", password=PASSWORD)

    assert issued.token == TOKEN
    assert TOKEN not in repr(issued)
    assert store.created_hash is not None
    assert TOKEN not in store.created_hash
    assert issued.principal.expires_at == NOW + timedelta(hours=8)


def test_wrong_password_records_failure_and_returns_generic_error() -> None:
    store = StoreStub(material())

    with pytest.raises(InvalidOperatorCredentialsError) as captured:
        service(store).login(login_name="admin", password="incorrect password")

    assert str(captured.value) == "operator credentials are invalid"
    assert store.failed_calls == [
        (OPERATOR_ID, LOCK_THRESHOLD, NOW + LOCK_DURATION)
    ]


def test_unknown_and_invalid_login_return_same_error_without_failure_update() -> None:
    for login_name in ("missing", "invalid login\n"):
        store = StoreStub(None)
        with pytest.raises(InvalidOperatorCredentialsError) as captured:
            service(store).login(login_name=login_name, password="anything")
        assert str(captured.value) == "operator credentials are invalid"
        assert store.failed_calls == []


def test_disabled_locked_and_malformed_hash_are_generic() -> None:
    base = material()
    cases = (
        replace(base, status=OperatorStatus.DISABLED),
        replace(base, locked_until=NOW + timedelta(minutes=1)),
        replace(base, password_hash="malformed"),
    )
    for current in cases:
        store = StoreStub(current)
        with pytest.raises(InvalidOperatorCredentialsError):
            service(store).login(login_name="admin", password=PASSWORD)


def test_resolve_and_logout_use_hash_without_echoing_token() -> None:
    store = StoreStub(material())
    issued = service(store).login(login_name="admin", password=PASSWORD)

    assert service(store).resolve(TOKEN) == issued.principal
    service(store).logout(TOKEN)

    assert store.revoked_hash == store.created_hash
    assert TOKEN not in (store.revoked_hash or "")


def test_invalid_token_is_rejected() -> None:
    store = StoreStub(material())
    with pytest.raises(InvalidOperatorSessionError):
        service(store).resolve("not valid")
