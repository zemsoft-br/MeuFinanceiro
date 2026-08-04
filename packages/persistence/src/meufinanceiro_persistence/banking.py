"""Public banking persistence contracts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar
from uuid import UUID

from meufinanceiro_security.errors import SecurityError
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.banking_models import (
    BankingConnectionRecord,
    BankingPersistenceError,
    CapabilitySnapshot,
    ConfigurationConflictError,
    ConfigurationNotFoundError,
    ConnectionCapabilityRecord,
    ConnectionConflictError,
    ConnectionNotFoundError,
    ProviderConfigurationRecord,
    ProviderConfigurationState,
    ProviderNotEnabledError,
    StoredCapability,
    StoredCapabilitySource,
    StoredCapabilityState,
    StoredConnectionStatus,
    clean_provider,
    clean_secret,
    credential_aad,
)
from meufinanceiro_persistence.banking_store import (
    BankingIntegrationStore as _BankingIntegrationStore,
)
from meufinanceiro_persistence.schema import provider_configurations

_Result = TypeVar("_Result")


@dataclass(frozen=True, slots=True, repr=False)
class EnabledProviderCredentials:
    """Ephemeral plaintext credentials passed only to a trusted operation callback."""

    configuration_id: UUID
    provider: str
    configuration_revision: int
    client_id: str
    client_secret: str

    def __post_init__(self) -> None:
        clean_provider(self.provider)
        if self.configuration_revision < 1:
            raise ValueError("configuration_revision must be positive")
        clean_secret(self.client_id, "client_id")
        clean_secret(self.client_secret, "client_secret")

    def __repr__(self) -> str:
        return (
            "EnabledProviderCredentials("
            f"provider={self.provider!r}, configuration_revision="
            f"{self.configuration_revision}, <redacted>)"
        )


class BankingIntegrationStore(_BankingIntegrationStore):
    """Public store boundary with sanitized database and credential failures."""

    def create_configuration(
        self,
        *,
        installation_id: UUID,
        provider: str,
        client_id: str,
        client_secret: str,
    ) -> ProviderConfigurationRecord:
        try:
            return super().create_configuration(
                installation_id=installation_id,
                provider=provider,
                client_id=client_id,
                client_secret=client_secret,
            )
        except BankingPersistenceError:
            raise
        except DBAPIError:
            raise BankingPersistenceError(
                "provider configuration could not be persisted"
            ) from None

    def use_enabled_credentials(
        self,
        *,
        installation_id: UUID,
        provider: str,
        operation: Callable[[EnabledProviderCredentials], _Result],
    ) -> _Result:
        """Run one trusted operation with credentials decrypted only for its lifetime."""

        normalized_provider = clean_provider(provider)
        if not callable(operation):
            raise TypeError("operation must be callable")
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    select(
                        func.set_config(
                            "app.current_installation_id",
                            str(installation_id),
                            True,
                        )
                    )
                )
                row = (
                    connection.execute(
                        select(
                            provider_configurations.c.id,
                            provider_configurations.c.provider,
                            provider_configurations.c.state,
                            provider_configurations.c.configuration_revision,
                            provider_configurations.c.client_id_envelope,
                            provider_configurations.c.client_secret_envelope,
                        ).where(
                            provider_configurations.c.installation_id
                            == installation_id,
                            provider_configurations.c.provider == normalized_provider,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except DBAPIError:
            raise BankingPersistenceError(
                "provider credentials could not be read"
            ) from None

        if row is None:
            raise ConfigurationNotFoundError("provider configuration was not found")
        if row["state"] != ProviderConfigurationState.ENABLED.value:
            raise ProviderNotEnabledError("provider is not enabled")

        configuration_id = row["id"]
        configuration_revision = row["configuration_revision"]
        client_id: str | None = None
        client_secret: str | None = None
        credentials: EnabledProviderCredentials | None = None
        try:
            client_id = clean_secret(
                self._cipher.decrypt_text(
                    row["client_id_envelope"],
                    aad=credential_aad(
                        installation_id,
                        normalized_provider,
                        configuration_id,
                        "client_id",
                    ),
                ),
                "client_id",
            )
            client_secret = clean_secret(
                self._cipher.decrypt_text(
                    row["client_secret_envelope"],
                    aad=credential_aad(
                        installation_id,
                        normalized_provider,
                        configuration_id,
                        "client_secret",
                    ),
                ),
                "client_secret",
            )
            credentials = EnabledProviderCredentials(
                configuration_id=configuration_id,
                provider=normalized_provider,
                configuration_revision=configuration_revision,
                client_id=client_id,
                client_secret=client_secret,
            )
        except (SecurityError, TypeError, ValueError):
            raise BankingPersistenceError(
                "provider credentials could not be decrypted"
            ) from None

        try:
            return operation(credentials)
        finally:
            credentials = None
            client_id = None
            client_secret = None


__all__ = [
    "BankingConnectionRecord",
    "BankingIntegrationStore",
    "BankingPersistenceError",
    "CapabilitySnapshot",
    "ConfigurationConflictError",
    "ConfigurationNotFoundError",
    "ConnectionCapabilityRecord",
    "ConnectionConflictError",
    "ConnectionNotFoundError",
    "EnabledProviderCredentials",
    "ProviderConfigurationRecord",
    "ProviderConfigurationState",
    "ProviderNotEnabledError",
    "StoredCapability",
    "StoredCapabilitySource",
    "StoredCapabilityState",
    "StoredConnectionStatus",
    "credential_aad",
]
