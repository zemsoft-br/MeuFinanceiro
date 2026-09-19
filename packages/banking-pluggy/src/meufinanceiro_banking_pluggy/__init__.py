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
from .loans import PluggyLoanSnapshot, PluggyLoansGateway
from .loans_http_gateway import (
    PluggyLoansGatewayHttpTransport,
    PluggyLoansHttpReadOnlyGateway,
    PluggyLoansPayloadTransport,
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
    "PluggyItemSnapshot",
    "PluggyLoanSnapshot",
    "PluggyLoansGateway",
    "PluggyLoansGatewayHttpTransport",
    "PluggyLoansHttpReadOnlyGateway",
    "PluggyLoansPayloadTransport",
    "PluggyReadOnlyGateway",
    "PluggyTransactionPageSnapshot",
    "PluggyTransactionSnapshot",
    "PluggyTransactionState",
    "parse_connected_item",
]

__version__ = "0.1.0"
