"""PostgreSQL store for local installation operators and opaque sessions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Engine, case, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.identity_models import (
    IdentityBootstrapConflictError,
    IdentityPersistenceError,
    InstallationOperatorRecord,
    OperatorAuthenticationMaterial,
    OperatorRole,
    OperatorSessionPrincipal,
    OperatorStatus,
    normalize_operator_login,
    require_aware,
    validate_token_hash,
)
from meufinanceiro_persistence.schema import (
    identity_installation,
    identity_operators,
    identity_sessions,
)


class OperatorIdentityStore:
    """Persist one local installation administrator and revocable sessions."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def bootstrap_installation_admin(
        self,
        *,
        login_name: str,
        password_hash: str,
    ) -> InstallationOperatorRecord:
        normalized_login = normalize_operator_login(login_name)
        if not isinstance(password_hash, str) or not password_hash:
            raise ValueError("password hash is invalid")
        installation_id = uuid4()
        operator_id = uuid4()
        try:
            with self._engine.begin() as connection:
                created_at = connection.execute(
                    select(func.transaction_timestamp())
                ).scalar_one()
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
                        login_name=normalized_login,
                        password_hash=password_hash,
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
        except IntegrityError:
            raise IdentityBootstrapConflictError(
                "installation administrator already exists"
            ) from None
        except DBAPIError:
            raise IdentityPersistenceError(
                "installation administrator could not be created"
            ) from None
        return InstallationOperatorRecord(
            installation_id=installation_id,
            operator_id=operator_id,
            login_name=normalized_login,
            role=OperatorRole.INSTALLATION_ADMIN,
            status=OperatorStatus.ACTIVE,
            created_at=created_at,
        )

    def get_authentication_material(
        self,
        *,
        login_name: str,
    ) -> OperatorAuthenticationMaterial | None:
        normalized_login = normalize_operator_login(login_name)
        try:
            with self._engine.begin() as connection:
                row = (
                    connection.execute(
                        select(
                            identity_operators.c.installation_id,
                            identity_operators.c.id,
                            identity_operators.c.login_name,
                            identity_operators.c.password_hash,
                            identity_operators.c.role,
                            identity_operators.c.status,
                            identity_operators.c.failed_attempts,
                            identity_operators.c.locked_until,
                        ).where(identity_operators.c.login_name == normalized_login)
                    )
                    .mappings()
                    .one_or_none()
                )
        except DBAPIError:
            raise IdentityPersistenceError(
                "operator authentication material could not be read"
            ) from None
        if row is None:
            return None
        return OperatorAuthenticationMaterial(
            installation_id=row["installation_id"],
            operator_id=row["id"],
            login_name=row["login_name"],
            password_hash=row["password_hash"],
            role=OperatorRole(row["role"]),
            status=OperatorStatus(row["status"]),
            failed_attempts=row["failed_attempts"],
            locked_until=row["locked_until"],
        )

    def record_failed_authentication(
        self,
        *,
        operator_id: UUID,
        lock_threshold: int,
        locked_until: datetime,
    ) -> None:
        if lock_threshold < 1:
            raise ValueError("lock_threshold must be positive")
        require_aware(locked_until, "locked_until")
        try:
            with self._engine.begin() as connection:
                result = connection.execute(
                    update(identity_operators)
                    .where(identity_operators.c.id == operator_id)
                    .values(
                        failed_attempts=identity_operators.c.failed_attempts + 1,
                        locked_until=case(
                            (
                                identity_operators.c.failed_attempts + 1
                                >= lock_threshold,
                                locked_until,
                            ),
                            else_=identity_operators.c.locked_until,
                        ),
                        updated_at=func.transaction_timestamp(),
                    )
                )
                if result.rowcount != 1:
                    raise IdentityPersistenceError(
                        "operator authentication state could not be updated"
                    )
        except IdentityPersistenceError:
            raise
        except DBAPIError:
            raise IdentityPersistenceError(
                "operator authentication state could not be updated"
            ) from None

    def create_session(
        self,
        *,
        material: OperatorAuthenticationMaterial,
        token_hash: str,
        expires_at: datetime,
        authenticated_at: datetime,
    ) -> OperatorSessionPrincipal:
        normalized_hash = validate_token_hash(token_hash)
        require_aware(expires_at, "expires_at")
        require_aware(authenticated_at, "authenticated_at")
        if expires_at <= authenticated_at:
            raise ValueError("session expiration must be in the future")
        session_id = uuid4()
        try:
            with self._engine.begin() as connection:
                operator_row = (
                    connection.execute(
                        update(identity_operators)
                        .where(
                            identity_operators.c.id == material.operator_id,
                            identity_operators.c.installation_id
                            == material.installation_id,
                            identity_operators.c.status == OperatorStatus.ACTIVE.value,
                        )
                        .values(
                            failed_attempts=0,
                            locked_until=None,
                            last_authenticated_at=authenticated_at,
                            updated_at=func.transaction_timestamp(),
                        )
                        .returning(
                            identity_operators.c.login_name,
                            identity_operators.c.role,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if operator_row is None:
                    raise IdentityPersistenceError(
                        "operator session could not be created"
                    )
                connection.execute(
                    identity_sessions.insert().values(
                        id=session_id,
                        installation_id=material.installation_id,
                        operator_id=material.operator_id,
                        token_hash=normalized_hash,
                        created_at=authenticated_at,
                        expires_at=expires_at,
                        last_seen_at=authenticated_at,
                        revoked_at=None,
                    )
                )
        except IdentityPersistenceError:
            raise
        except IntegrityError:
            raise IdentityPersistenceError(
                "operator session could not be created"
            ) from None
        except DBAPIError:
            raise IdentityPersistenceError(
                "operator session could not be created"
            ) from None
        return OperatorSessionPrincipal(
            session_id=session_id,
            installation_id=material.installation_id,
            operator_id=material.operator_id,
            login_name=operator_row["login_name"],
            role=OperatorRole(operator_row["role"]),
            expires_at=expires_at,
        )

    def resolve_session(
        self,
        *,
        token_hash: str,
        observed_at: datetime,
    ) -> OperatorSessionPrincipal | None:
        normalized_hash = validate_token_hash(token_hash)
        require_aware(observed_at, "observed_at")
        try:
            with self._engine.begin() as connection:
                row = (
                    connection.execute(
                        select(
                            identity_sessions.c.id.label("session_id"),
                            identity_sessions.c.installation_id,
                            identity_sessions.c.operator_id,
                            identity_sessions.c.expires_at,
                            identity_operators.c.login_name,
                            identity_operators.c.role,
                        )
                        .select_from(
                            identity_sessions.join(
                                identity_operators,
                                (
                                    identity_sessions.c.operator_id
                                    == identity_operators.c.id
                                )
                                & (
                                    identity_sessions.c.installation_id
                                    == identity_operators.c.installation_id
                                ),
                            )
                        )
                        .where(
                            identity_sessions.c.token_hash == normalized_hash,
                            identity_sessions.c.revoked_at.is_(None),
                            identity_sessions.c.expires_at > observed_at,
                            identity_operators.c.status == OperatorStatus.ACTIVE.value,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is not None:
                    connection.execute(
                        update(identity_sessions)
                        .where(identity_sessions.c.id == row["session_id"])
                        .values(last_seen_at=observed_at)
                    )
        except DBAPIError:
            raise IdentityPersistenceError(
                "operator session could not be resolved"
            ) from None
        if row is None:
            return None
        return OperatorSessionPrincipal(
            session_id=row["session_id"],
            installation_id=row["installation_id"],
            operator_id=row["operator_id"],
            login_name=row["login_name"],
            role=OperatorRole(row["role"]),
            expires_at=row["expires_at"],
        )

    def revoke_session(
        self,
        *,
        token_hash: str,
        revoked_at: datetime,
    ) -> None:
        normalized_hash = validate_token_hash(token_hash)
        require_aware(revoked_at, "revoked_at")
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    update(identity_sessions)
                    .where(
                        identity_sessions.c.token_hash == normalized_hash,
                        identity_sessions.c.revoked_at.is_(None),
                    )
                    .values(revoked_at=revoked_at, last_seen_at=revoked_at)
                )
        except DBAPIError:
            raise IdentityPersistenceError(
                "operator session could not be revoked"
            ) from None
