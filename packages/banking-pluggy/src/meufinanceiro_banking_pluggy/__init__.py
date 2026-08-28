"""Read-only Pluggy adapter contracts for MeuFinanceiro."""

from .adapter import PluggyBankingProvider
from .bills import (
    PluggyCreditCardBillSnapshot,
    PluggyCreditCardBillsGateway,
    PluggyCreditCardBillState,
)
from .bills_http_gateway import (
    PluggyBillsGatewayHttpTransport,
    PluggyBillsHttpReadOnlyGateway,
    PluggyBillsPayloadTransport,
)
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

__all__ = [
    "PluggyAccountKind",
    "PluggyAccountSnapshot",
    "PluggyBankingProvider",
    "PluggyBillsGatewayHttpTransport",
    "PluggyBillsHttpReadOnlyGateway",
    "PluggyBillsPayloadTransport",
    "PluggyCapability",
    "PluggyCapabilityAvailability",
    "PluggyCapabilityEvidence",
    "PluggyCapabilitySnapshot",
    "PluggyConnectTokenHttpTransport",
    "PluggyConnectionPhase",
    "PluggyCreditCardBillSnapshot",
    "PluggyCreditCardBillsGateway",
    "PluggyCreditCardBillState",
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
    "parse_connected_item",
]

__version__ = "0.1.0"
