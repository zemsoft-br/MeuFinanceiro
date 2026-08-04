"""Read-only Pluggy adapter contracts for MeuFinanceiro."""

from .adapter import PluggyBankingProvider
from .gateway import (
    PluggyAccountKind,
    PluggyAccountSnapshot,
    PluggyCapability,
    PluggyCapabilityAvailability,
    PluggyCapabilityEvidence,
    PluggyCapabilitySnapshot,
    PluggyConnectionPhase,
    PluggyGatewayError,
    PluggyGatewayErrorCategory,
    PluggyInstallmentSnapshot,
    PluggyItemSnapshot,
    PluggyReadOnlyGateway,
    PluggyTransactionPageSnapshot,
    PluggyTransactionSnapshot,
    PluggyTransactionState,
)
from .http_gateway import PluggyGatewayHttpTransport, PluggyHttpReadOnlyGateway

__all__ = [
    "PluggyAccountKind",
    "PluggyAccountSnapshot",
    "PluggyBankingProvider",
    "PluggyCapability",
    "PluggyCapabilityAvailability",
    "PluggyCapabilityEvidence",
    "PluggyCapabilitySnapshot",
    "PluggyConnectionPhase",
    "PluggyGatewayError",
    "PluggyGatewayErrorCategory",
    "PluggyGatewayHttpTransport",
    "PluggyHttpReadOnlyGateway",
    "PluggyInstallmentSnapshot",
    "PluggyItemSnapshot",
    "PluggyReadOnlyGateway",
    "PluggyTransactionPageSnapshot",
    "PluggyTransactionSnapshot",
    "PluggyTransactionState",
]

__version__ = "0.1.0"
