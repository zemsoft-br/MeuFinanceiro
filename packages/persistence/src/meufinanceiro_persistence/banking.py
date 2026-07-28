"""Public banking persistence contracts."""

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
from meufinanceiro_persistence.banking_store import BankingIntegrationStore

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
