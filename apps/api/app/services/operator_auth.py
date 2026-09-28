"""Local operator authentication with opaque, revocable bearer sessions."""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn, Protocol, runtime_checkable
from uuid import UUID

from meufinanceiro_persistence import (
    IdentityPersistenceError,
    OperatorAuthenticationMaterial,
    OperatorSessionPrincipal,
    OperatorStatus,
    normalize_operator_login,
)
from meufinanceiro_security.errors import PasswordHashError
from meufinanceiro_security.passwords import PasswordService

_SESSION_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,128}$")
_DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$Q6pnnNZlBaNyPFACvNTVzA$"
    "Ymqkg7Y+dhzhaC7kDP5L1fYibyR5CiFz1IBiMaLmx/I"
)
SESSION_TTL = timedelta(hours=8)
LOCK_THRESHOLD = 5
LOCK_DURATION = timedelta(minutes=15)
MINIMUM_PASSWORD_LENGTH = 12
MAXIMUM_PASSWORD_LENGTH = 1024


class OperatorAuthenticationError(RuntimeError):
    """Base sanitized authentication error."""


class InvalidOperatorCredentialsError(OperatorAuthenticationError):
    pass


class InvalidOperatorSessionError(OperatorAuthenticationError):
    pass


class OperatorAuthenticationUnavailableError(OperatorAuthenticationError):
    pass


@runtime_checkable
class OperatorAuthenticationStore(Protocol):
    def get_authentication_material(
        self, *, login_name: str
    ) -> OperatorAuthenticationMaterial | None: ...

    def record_failed_authentication(
        self,
        *,
        operator_id: UUID,
        lock_threshold: int,
        locked_until: datetime,
    ) -> None: ...

    def create_session(
        self,
        *,
        material: OperatorAuthenticationMaterial,
        token_hash: str,
        expires_at: datetime,
        authenticated_at: datetime,
    ) -> OperatorSessionPrincipal: ...

    def resolve_session(
        self,
        *,
        token_hash: str,
        observed_at: datetime,
    ) -> OperatorSessionPrincipal | None: ...

    def revoke_session(
        self,
        *,
        token_hash: str,
        revoked_at: datetime,
    ) -> None: ...


@dataclass(frozen=True, slots=True, repr=False)
class IssuedOperatorSession:
    token: str
    principal: OperatorSessionPrincipal

    def __repr__(self) -> str:
        return f"IssuedOperatorSession(principal={self.principal!r}, token=<redacted>)"


def validate_operator_password(password: str) -> str:
    if not isinstance(password, str):
        raise TypeError("password must be a string")
    if not MINIMUM_PASSWORD_LENGTH <= len(password) <= MAXIMUM_PASSWORD_LENGTH:
        raise ValueError("password length is invalid")
    if not password.strip():
        raise ValueError("password must contain a visible character")
    if any(ord(character) < 32 or ord(character) == 127 for character in password):
        raise ValueError("password contains control characters")
    return password


def _token_hash(token: str) -> str:
    if not isinstance(token, str) or not _SESSION_TOKEN_PATTERN.fullmatch(token):
        raise InvalidOperatorSessionError("operator session is invalid")
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class OperatorAuthenticationService:
    """Authenticate the installation administrator without user enumeration."""

    def __init__(
        self,
        store: OperatorAuthenticationStore,
        *,
        password_service: PasswordService | None = None,
        clock: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(store, OperatorAuthenticationStore):
            raise TypeError("store must satisfy OperatorAuthenticationStore")
        self._store = store
        self._password_service = password_service or PasswordService()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))

    def login(self, *, login_name: str, password: str) -> IssuedOperatorSession:
        now = self._aware_now()
        try:
            normalized_login = normalize_operator_login(login_name)
        except (TypeError, ValueError):
            self._verify_dummy(password)
            self._invalid_credentials()

        try:
            material = self._store.get_authentication_material(
                login_name=normalized_login
            )
        except IdentityPersistenceError:
            self._unavailable()

        if material is None:
            self._verify_dummy(password)
            self._invalid_credentials()

        verified = self._verify_material(material, password)
        is_locked = material.locked_until is not None and material.locked_until > now
        if material.status is not OperatorStatus.ACTIVE or is_locked or not verified:
            if material.status is OperatorStatus.ACTIVE and not is_locked:
                try:
                    self._store.record_failed_authentication(
                        operator_id=material.operator_id,
                        lock_threshold=LOCK_THRESHOLD,
                        locked_until=now + LOCK_DURATION,
                    )
                except IdentityPersistenceError:
                    self._unavailable()
            self._invalid_credentials()

        token = self._token_factory()
        try:
            token_hash = _token_hash(token)
            principal = self._store.create_session(
                material=material,
                token_hash=token_hash,
                expires_at=now + SESSION_TTL,
                authenticated_at=now,
            )
        except InvalidOperatorSessionError:
            self._unavailable()
        except IdentityPersistenceError:
            self._unavailable()
        return IssuedOperatorSession(token=token, principal=principal)

    def resolve(self, token: str) -> OperatorSessionPrincipal:
        now = self._aware_now()
        try:
            token_hash = _token_hash(token)
            principal = self._store.resolve_session(
                token_hash=token_hash,
                observed_at=now,
            )
        except InvalidOperatorSessionError:
            raise
        except IdentityPersistenceError:
            self._unavailable()
        if principal is None:
            raise InvalidOperatorSessionError("operator session is invalid")
        return principal

    def logout(self, token: str) -> None:
        now = self._aware_now()
        try:
            self._store.revoke_session(
                token_hash=_token_hash(token),
                revoked_at=now,
            )
        except InvalidOperatorSessionError:
            raise
        except IdentityPersistenceError:
            self._unavailable()

    def _verify_material(
        self,
        material: OperatorAuthenticationMaterial,
        password: str,
    ) -> bool:
        try:
            return self._password_service.verify(material.password_hash, password)
        except (PasswordHashError, TypeError, ValueError):
            return False

    def _verify_dummy(self, password: str) -> None:
        candidate = password if isinstance(password, str) else ""
        try:
            self._password_service.verify(_DUMMY_PASSWORD_HASH, candidate)
        except PasswordHashError:
            self._unavailable()

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("authentication clock must be timezone-aware")
        return value

    @staticmethod
    def _invalid_credentials() -> NoReturn:
        raise InvalidOperatorCredentialsError("operator credentials are invalid")

    @staticmethod
    def _unavailable() -> NoReturn:
        raise OperatorAuthenticationUnavailableError(
            "operator authentication is unavailable"
        ) from None
