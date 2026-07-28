"""Public banking persistence contracts."""

from __future__ import annotations

from uuid import UUID

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
    credential_aad,
)
from meufinanceiro_persistence.banking_store import (
    BankingIntegrationStore as _BankingIntegrationStore,
)


class BankingIntegrationStore(_BankingIntegrationStore):
    """Public store boundary with sanitized database failures."""

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
    "ProviderConfigurationRecord",
    "ProviderConfigurationState",
    "ProviderNotEnabledError",
    "StoredCapability",
    "StoredCapabilitySource",
    "StoredCapabilityState",
    "StoredConnectionStatus",
    "credential_aad",
]
