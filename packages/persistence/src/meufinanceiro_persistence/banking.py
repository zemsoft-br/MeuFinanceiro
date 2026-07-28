"""Transactional persistence for banking provider configuration and connections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, NoReturn
from uuid import UUID, uuid4

from meufinanceiro_security.envelope import SecretCipher
from sqlalchemy import Connection, Engine, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.schema import (
    connection_capabilities,
    connections,
    provider_configurations,
)

_PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_REASON_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MAX_EXTERNAL_ID = 512
_MAX_SECRET_LENGTH = 16_384


class ProviderConfigurationState(StrEnum):
    DISABLED = "disabled"
    CONFIGURED = "configured"
    ENABLED = "enabled"


class StoredConnectionStatus(StrEnum):
    PENDING_USER_ACTION = "PENDING_USER_ACTION"
    SYNC_REQUESTED = "SYNC_REQUESTED"
    SYNCING = "SYNCING"
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    REAUTHENTICATION_REQUIRED = "REAUTHENTICATION_REQUIRED"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    DISCONNECTED = "DISCONNECTED"
    FAILED = "FAILED"


class StoredCapability(StrEnum):
    IDENTITY = "identity"
    BANK_ACCOUNTS = "bank_accounts"
    CREDIT_ACCOUNTS = "credit_accounts"
    TRANSACTIONS = "transactions"
    CREDIT_CARD_BILLS = "credit_card_bills"
    INVESTMENTS = "investments"
    LOANS = "loans"
    MANUAL_REFRESH = "manual_refresh"
    CONSENT_RENEWAL = "consent_renewal"
    DISCONNECT = "disconnect"
    WEBHOOKS = "webhooks"


class StoredCapabilityState(StrEnum):
    SUPPORTED = "SUPPORTED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    REQUIRES_USER_ACTION = "REQUIRES_USER_ACTION"
    NOT_OBSERVED = "NOT_OBSERVED"
    UNKNOWN = "UNKNOWN"


class StoredCapabilitySource(StrEnum):
    CONTRACT = "CONTRACT"
    OBSERVATION = "OBSERVATION"
    OPERATION = "OPERATION"


class BankingPersistenceError(RuntimeError):
    """Base error that never includes credentials or external identifiers."""


class ConfigurationNotFoundError(BankingPersistenceError):
    pass


class ConfigurationConflictError(BankingPersistenceError):
    pass


class ProviderNotEnabledError(BankingPersistenceError):
    pass


class ConnectionNotFoundError(BankingPersistenceError):
    pass


class ConnectionConflictError(BankingPersistenceError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderConfigurationRecord:
    id: UUID
    installation_id: UUID
    provider: str
    state: ProviderConfigurationState
    configuration_revision: int
    created_at: datetime
    updated_at: datetime
    enabled_at: datetime | None
    disabled_at: datetime | None


@dataclass(frozen=True, slots=True)
class BankingConnectionRecord:
    id: UUID
    installation_id: UUID
    residence_id: UUID
    provider: str
    external_connection_id: str
    status: StoredConnectionStatus
    requires_user_action: bool
    last_successful_sync_at: datetime | None
    last_attempt_at: datetime | None
    next_refresh_allowed_at: datetime | None
    consent_expires_at: datetime | None
    provider_reason_code: str | None
    disconnected_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CapabilitySnapshot:
    capability: StoredCapability
    state: StoredCapabilityState
    source: StoredCapabilitySource
    observed_at: datetime
    provider_reason_code: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.observed_at, "observed_at")
        _clean_reason_code(self.provider_reason_code)


@dataclass(frozen=True, slots=True)
class ConnectionCapabilityRecord:
    id: UUID
    residence_id: UUID
    connection_id: UUID
    capability: StoredCapability
    state: StoredCapabilityState
    source: StoredCapabilitySource
    provider_reason_code: str | None
    observed_at: datetime
    updated_at: datetime


_PROVIDER_PUBLIC_COLUMNS = (
    provider_configurations.c.id,
    provider_configurations.c.installation_id,
    provider_configurations.c.provider,
    provider_configurations.c.state,
    provider_configurations.c.configuration_revision,
    provider_configurations.c.created_at,
    provider_configurations.c.updated_at,
    provider_configurations.c.enabled_at,
    provider_configurations.c.disabled_at,
)

_CONNECTION_PUBLIC_COLUMNS = (
    connections.c.id,
    connections.c.installation_id,
    connections.c.residence_id,
    connections.c.provider,
    connections.c.external_connection_id,
    connections.c.status,
    connections.c.requires_user_action,
    connections.c.last_successful_sync_at,
    connections.c.last_attempt_at,
    connections.c.next_refresh_allowed_at,
    connections.c.consent_expires_at,
    connections.c.provider_reason_code,
    connections.c.disconnected_at,
    connections.c.created_at,
    connections.c.updated_at,
)

_CAPABILITY_PUBLIC_COLUMNS = (
    connection_capabilities.c.id,
    connection_capabilities.c.residence_id,
    connection_capabilities.c.connection_id,
    connection_capabilities.c.capability,
    connection_capabilities.c.state,
    connection_capabilities.c.source,
    connection_capabilities.c.provider_reason_code,
    connection_capabilities.c.observed_at,
    connection_capabilities.c.updated_at,
)


def credential_aad(
    installation_id: UUID,
    provider: str,
    configuration_id: UUID,
    field_name: str,
) -> str:
    normalized_provider = _clean_provider(provider)
    if field_name not in {"client_id", "client_secret"}:
        raise ValueError("credential field is not supported")
    return (
        f"meufinanceiro:v1:installation:{installation_id}:"
        f"provider:{normalized_provider}:configuration:{configuration_id}:"
        f"field:{field_name}"
    )


class BankingIntegrationStore:
    """Persist encrypted provider configuration and residence-scoped observations."""

    def __init__(self, engine: Engine, cipher: SecretCipher) -> None:
        self._engine = engine
        self._cipher = cipher

    def create_configuration(
        self,
        *,
        installation_id: UUID,
        provider: str,
        client_id: str,
        client_secret: str,
    ) -> ProviderConfigurationRecord:
        normalized_provider = _clean_provider(provider)
        configuration_id = uuid4()
        client_id_envelope = self._cipher.encrypt(
            _clean_secret(client_id, "client_id"),
            aad=credential_aad(
                installation_id,
                normalized_provider,
                configuration_id,
                "client_id",
            ),
        )
        client_secret_envelope = self._cipher.encrypt(
            _clean_secret(client_secret, "client_secret"),
            aad=credential_aad(
                installation_id,
                normalized_provider,
                configuration_id,
                "client_secret",
            ),
        )
        with self._engine.begin() as connection:
            _set_context(connection, installation_id=installation_id)
            try:
                row = (
                    connection.execute(
                        provider_configurations.insert()
                        .values(
                            id=configuration_id,
                            installation_id=installation_id,
                            provider=normalized_provider,
                            state=ProviderConfigurationState.CONFIGURED.value,
                            client_id_envelope=client_id_envelope,
                            client_secret_envelope=client_secret_envelope,
                            configuration_revision=1,
                            created_at=func.transaction_timestamp(),
                            updated_at=func.transaction_timestamp(),
                            enabled_at=None,
                            disabled_at=None,
                        )
                        .returning(*_PROVIDER_PUBLIC_COLUMNS)
                    )
                    .mappings()
                    .one()
                )
            except IntegrityError as error:
                raise ConfigurationConflictError(
                    "provider configuration already exists"
                ) from error
        return _provider_record(row)

    def get_configuration(
        self,
        *,
        installation_id: UUID,
        provider: str,
    ) -> ProviderConfigurationRecord:
        normalized_provider = _clean_provider(provider)
        with self._engine.begin() as connection:
            _set_context(connection, installation_id=installation_id)
            row = (
                connection.execute(
                    select(*_PROVIDER_PUBLIC_COLUMNS).where(
                        provider_configurations.c.installation_id == installation_id,
                        provider_configurations.c.provider == normalized_provider,
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise ConfigurationNotFoundError("provider configuration was not found")
        return _provider_record(row)

    def set_configuration_state(
        self,
        *,
        installation_id: UUID,
        provider: str,
        expected_revision: int,
        state: ProviderConfigurationState,
    ) -> ProviderConfigurationRecord:
        if expected_revision < 1:
            raise ValueError("expected_revision must be positive")
        normalized_provider = _clean_provider(provider)
        values: dict[str, Any] = {
            "state": state.value,
            "configuration_revision": (
                provider_configurations.c.configuration_revision + 1
            ),
            "updated_at": func.transaction_timestamp(),
        }
        if state is ProviderConfigurationState.ENABLED:
            values.update(
                enabled_at=func.transaction_timestamp(),
                disabled_at=None,
            )
        elif state is ProviderConfigurationState.DISABLED:
            values.update(disabled_at=func.transaction_timestamp())
        else:
            values.update(enabled_at=None, disabled_at=None)

        with self._engine.begin() as connection:
            _set_context(connection, installation_id=installation_id)
            row = (
                connection.execute(
                    update(provider_configurations)
                    .where(
                        provider_configurations.c.installation_id == installation_id,
                        provider_configurations.c.provider == normalized_provider,
                        provider_configurations.c.configuration_revision
                        == expected_revision,
                    )
                    .values(**values)
                    .returning(*_PROVIDER_PUBLIC_COLUMNS)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                self._raise_configuration_write_error(
                    connection,
                    installation_id=installation_id,
                    provider=normalized_provider,
                )
        return _provider_record(row)

    def replace_credentials(
        self,
        *,
        installation_id: UUID,
        provider: str,
        expected_revision: int,
        client_id: str,
        client_secret: str,
    ) -> ProviderConfigurationRecord:
        current = self.get_configuration(
            installation_id=installation_id,
            provider=provider,
        )
        if current.configuration_revision != expected_revision:
            raise ConfigurationConflictError("provider configuration revision changed")
        client_id_envelope = self._cipher.encrypt(
            _clean_secret(client_id, "client_id"),
            aad=credential_aad(
                installation_id,
                current.provider,
                current.id,
                "client_id",
            ),
        )
        client_secret_envelope = self._cipher.encrypt(
            _clean_secret(client_secret, "client_secret"),
            aad=credential_aad(
                installation_id,
                current.provider,
                current.id,
                "client_secret",
            ),
        )

        with self._engine.begin() as connection:
            _set_context(connection, installation_id=installation_id)
            row = (
                connection.execute(
                    update(provider_configurations)
                    .where(
                        provider_configurations.c.id == current.id,
                        provider_configurations.c.installation_id == installation_id,
                        provider_configurations.c.provider == current.provider,
                        provider_configurations.c.configuration_revision
                        == expected_revision,
                    )
                    .values(
                        client_id_envelope=client_id_envelope,
                        client_secret_envelope=client_secret_envelope,
                        configuration_revision=(
                            provider_configurations.c.configuration_revision + 1
                        ),
                        updated_at=func.transaction_timestamp(),
                    )
                    .returning(*_PROVIDER_PUBLIC_COLUMNS)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                self._raise_configuration_write_error(
                    connection,
                    installation_id=installation_id,
                    provider=current.provider,
                )
        return _provider_record(row)

    def register_connection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        provider: str,
        external_connection_id: str,
        status: StoredConnectionStatus,
        requires_user_action: bool,
        last_successful_sync_at: datetime | None = None,
        last_attempt_at: datetime | None = None,
        next_refresh_allowed_at: datetime | None = None,
        consent_expires_at: datetime | None = None,
        provider_reason_code: str | None = None,
        disconnected_at: datetime | None = None,
    ) -> BankingConnectionRecord:
        normalized_provider = _clean_provider(provider)
        normalized_external_id = _clean_external_id(external_connection_id)
        normalized_reason = _clean_reason_code(provider_reason_code)
        for field_name, value in (
            ("last_successful_sync_at", last_successful_sync_at),
            ("last_attempt_at", last_attempt_at),
            ("next_refresh_allowed_at", next_refresh_allowed_at),
            ("consent_expires_at", consent_expires_at),
            ("disconnected_at", disconnected_at),
        ):
            _require_aware(value, field_name)
        _validate_connection_state(
            status=status,
            requires_user_action=requires_user_action,
            disconnected_at=disconnected_at,
        )

        with self._engine.begin() as connection:
            _set_context(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
            )
            configuration = (
                connection.execute(
                    select(
                        provider_configurations.c.id,
                        provider_configurations.c.state,
                    ).where(
                        provider_configurations.c.installation_id == installation_id,
                        provider_configurations.c.provider == normalized_provider,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if configuration is None:
                raise ConfigurationNotFoundError(
                    "provider configuration was not found"
                )
            if configuration["state"] != ProviderConfigurationState.ENABLED.value:
                raise ProviderNotEnabledError("provider is not enabled")

            statement = postgresql_insert(connections).values(
                id=uuid4(),
                installation_id=installation_id,
                residence_id=residence_id,
                provider=normalized_provider,
                provider_configuration_id=configuration["id"],
                external_connection_id=normalized_external_id,
                status=status.value,
                requires_user_action=requires_user_action,
                last_successful_sync_at=last_successful_sync_at,
                last_attempt_at=last_attempt_at,
                next_refresh_allowed_at=next_refresh_allowed_at,
                consent_expires_at=consent_expires_at,
                provider_reason_code=normalized_reason,
                disconnected_at=disconnected_at,
                created_at=func.transaction_timestamp(),
                updated_at=func.transaction_timestamp(),
            )
            statement = statement.on_conflict_do_update(
                index_elements=[
                    connections.c.installation_id,
                    connections.c.provider,
                    connections.c.external_connection_id,
                ],
                set_={
                    "provider_configuration_id": configuration["id"],
                    "status": status.value,
                    "requires_user_action": requires_user_action,
                    "last_successful_sync_at": last_successful_sync_at,
                    "last_attempt_at": last_attempt_at,
                    "next_refresh_allowed_at": next_refresh_allowed_at,
                    "consent_expires_at": consent_expires_at,
                    "provider_reason_code": normalized_reason,
                    "disconnected_at": disconnected_at,
                    "updated_at": func.transaction_timestamp(),
                },
                where=connections.c.residence_id == residence_id,
            ).returning(*_CONNECTION_PUBLIC_COLUMNS)
            try:
                row = connection.execute(statement).mappings().one_or_none()
            except DBAPIError as error:
                raise ConnectionConflictError(
                    "external connection is already assigned"
                ) from error
            if row is None:
                raise ConnectionConflictError(
                    "external connection is already assigned"
                )
        return _connection_record(row)

    def get_connection(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
    ) -> BankingConnectionRecord:
        with self._engine.begin() as connection:
            _set_context(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
            )
            row = (
                connection.execute(
                    select(*_CONNECTION_PUBLIC_COLUMNS).where(
                        connections.c.id == connection_id,
                        connections.c.installation_id == installation_id,
                        connections.c.residence_id == residence_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise ConnectionNotFoundError("banking connection was not found")
        return _connection_record(row)

    def replace_capabilities(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        connection_id: UUID,
        snapshots: tuple[CapabilitySnapshot, ...],
    ) -> tuple[ConnectionCapabilityRecord, ...]:
        normalized = tuple(snapshots)
        capabilities = [snapshot.capability for snapshot in normalized]
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("capability snapshot contains duplicates")

        with self._engine.begin() as connection:
            _set_context(
                connection,
                installation_id=installation_id,
                residence_id=residence_id,
            )
            visible_connection = connection.scalar(
                select(connections.c.id).where(
                    connections.c.id == connection_id,
                    connections.c.installation_id == installation_id,
                    connections.c.residence_id == residence_id,
                )
            )
            if visible_connection is None:
                raise ConnectionNotFoundError("banking connection was not found")

            if capabilities:
                connection.execute(
                    delete(connection_capabilities).where(
                        connection_capabilities.c.connection_id == connection_id,
                        connection_capabilities.c.capability.not_in(
                            [capability.value for capability in capabilities]
                        ),
                    )
                )
            else:
                connection.execute(
                    delete(connection_capabilities).where(
                        connection_capabilities.c.connection_id == connection_id
                    )
                )

            for snapshot in normalized:
                statement = postgresql_insert(connection_capabilities).values(
                    id=uuid4(),
                    residence_id=residence_id,
                    connection_id=connection_id,
                    capability=snapshot.capability.value,
                    state=snapshot.state.value,
                    source=snapshot.source.value,
                    provider_reason_code=snapshot.provider_reason_code,
                    observed_at=snapshot.observed_at,
                    updated_at=func.transaction_timestamp(),
                )
                connection.execute(
                    statement.on_conflict_do_update(
                        index_elements=[
                            connection_capabilities.c.connection_id,
                            connection_capabilities.c.capability,
                        ],
                        set_={
                            "state": snapshot.state.value,
                            "source": snapshot.source.value,
                            "provider_reason_code": snapshot.provider_reason_code,
                            "observed_at": snapshot.observed_at,
                            "updated_at": func.transaction_timestamp(),
                        },
                    )
                )

            rows = (
                connection.execute(
                    select(*_CAPABILITY_PUBLIC_COLUMNS)
                    .where(connection_capabilities.c.connection_id == connection_id)
                    .order_by(connection_capabilities.c.capability)
                )
                .mappings()
                .all()
            )
        return tuple(_capability_record(row) for row in rows)

    def _raise_configuration_write_error(
        self,
        connection: Connection,
        *,
        installation_id: UUID,
        provider: str,
    ) -> NoReturn:
        exists = connection.scalar(
            select(provider_configurations.c.id).where(
                provider_configurations.c.installation_id == installation_id,
                provider_configurations.c.provider == provider,
            )
        )
        if exists is None:
            raise ConfigurationNotFoundError("provider configuration was not found")
        raise ConfigurationConflictError("provider configuration revision changed")


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


def _clean_provider(provider: str) -> str:
    if not isinstance(provider, str) or not _PROVIDER_PATTERN.fullmatch(provider):
        raise ValueError("provider slug is invalid")
    return provider


def _clean_secret(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must not be empty")
    if len(value) > _MAX_SECRET_LENGTH:
        raise ValueError(f"{field_name} exceeds the supported size")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field_name} contains control characters")
    return value


def _clean_external_id(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("external connection id must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_EXTERNAL_ID:
        raise ValueError("external connection id size is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ValueError("external connection id contains control characters")
    return normalized


def _clean_reason_code(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _REASON_PATTERN.fullmatch(value):
        raise ValueError("provider reason code is invalid")
    return value


def _require_aware(value: datetime | None, field_name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{field_name} must be timezone-aware")


def _validate_connection_state(
    *,
    status: StoredConnectionStatus,
    requires_user_action: bool,
    disconnected_at: datetime | None,
) -> None:
    expected_user_action = status in {
        StoredConnectionStatus.PENDING_USER_ACTION,
        StoredConnectionStatus.REAUTHENTICATION_REQUIRED,
    }
    if expected_user_action and not requires_user_action:
        raise ValueError("connection status requires user action")
    if status is StoredConnectionStatus.DISCONNECTED:
        if requires_user_action or disconnected_at is None:
            raise ValueError("disconnected connection state is invalid")


def _provider_record(row: RowMapping) -> ProviderConfigurationRecord:
    return ProviderConfigurationRecord(
        id=row["id"],
        installation_id=row["installation_id"],
        provider=row["provider"],
        state=ProviderConfigurationState(row["state"]),
        configuration_revision=row["configuration_revision"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        enabled_at=row["enabled_at"],
        disabled_at=row["disabled_at"],
    )


def _connection_record(row: RowMapping) -> BankingConnectionRecord:
    return BankingConnectionRecord(
        id=row["id"],
        installation_id=row["installation_id"],
        residence_id=row["residence_id"],
        provider=row["provider"],
        external_connection_id=row["external_connection_id"],
        status=StoredConnectionStatus(row["status"]),
        requires_user_action=row["requires_user_action"],
        last_successful_sync_at=row["last_successful_sync_at"],
        last_attempt_at=row["last_attempt_at"],
        next_refresh_allowed_at=row["next_refresh_allowed_at"],
        consent_expires_at=row["consent_expires_at"],
        provider_reason_code=row["provider_reason_code"],
        disconnected_at=row["disconnected_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _capability_record(row: RowMapping) -> ConnectionCapabilityRecord:
    return ConnectionCapabilityRecord(
        id=row["id"],
        residence_id=row["residence_id"],
        connection_id=row["connection_id"],
        capability=StoredCapability(row["capability"]),
        state=StoredCapabilityState(row["state"]),
        source=StoredCapabilitySource(row["source"]),
        provider_reason_code=row["provider_reason_code"],
        observed_at=row["observed_at"],
        updated_at=row["updated_at"],
    )
