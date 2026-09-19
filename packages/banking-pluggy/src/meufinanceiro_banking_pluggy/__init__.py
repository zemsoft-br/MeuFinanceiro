"""Read-only Pluggy adapter contracts for MeuFinanceiro."""

from .adapter import PluggyBankingProvider
from .connect_token import PluggyConnectTokenHttpTransport
from .connected_item import parse_connected_item
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
from .investments import PluggyInvestmentSnapshot, PluggyInvestmentsGateway
from .investments_http_gateway import (
    PluggyInvestmentsGatewayHttpTransport,
    PluggyInvestmentsHttpReadOnlyGateway,
    PluggyInvestmentsPayloadTransport,
)

__all__ = [
    "PluggyAccountKind",
    "PluggyAccountSnapshot",
    "PluggyBankingProvider",
    "PluggyCapability",
    "PluggyCapabilityAvailability",
    "PluggyCapabilityEvidence",
    "PluggyCapabilitySnapshot",
    "PluggyConnectTokenHttpTransport",
    "PluggyConnectionPhase",
    "PluggyGatewayError",
    "PluggyGatewayErrorCategory",
    "PluggyGatewayHttpTransport",
    "PluggyHttpReadOnlyGateway",
    "PluggyInstallmentSnapshot",
    "PluggyInvestmentSnapshot",
    "PluggyInvestmentsGateway",
    "PluggyInvestmentsGatewayHttpTransport",
    "PluggyInvestmentsHttpReadOnlyGateway",
    "PluggyInvestmentsPayloadTransport",
    "PluggyItemSnapshot",
    "PluggyReadOnlyGateway",
    "PluggyTransactionPageSnapshot",
    "PluggyTransactionSnapshot",
    "PluggyTransactionState",
    "parse_connected_item",
]

__version__ = "0.1.0"
