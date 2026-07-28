"""Provider-neutral banking integration contracts for MeuFinanceiro."""

from .fake import FakeBankingProvider
from .models import (
    AccountType,
    Capability,
    CapabilitySource,
    CapabilityState,
    ConnectionCapability,
    ConnectionIntent,
    ConnectionIntentKind,
    ConnectionState,
    ConnectionStatus,
    CreditCardBillStatus,
    ExternalAccount,
    ExternalCreditCardBill,
    ExternalInvestment,
    ExternalLoan,
    ExternalPage,
    ExternalTransaction,
    InstallmentMetadata,
    RefreshRequest,
    RefreshStatus,
    TransactionStatus,
)
from .provider import BankingProvider, BankingProviderError, ProviderErrorCategory

__all__ = [
    "AccountType",
    "BankingProvider",
    "BankingProviderError",
    "Capability",
    "CapabilitySource",
    "CapabilityState",
    "ConnectionCapability",
    "ConnectionIntent",
    "ConnectionIntentKind",
    "ConnectionState",
    "ConnectionStatus",
    "CreditCardBillStatus",
    "ExternalAccount",
    "ExternalCreditCardBill",
    "ExternalInvestment",
    "ExternalLoan",
    "ExternalPage",
    "ExternalTransaction",
    "FakeBankingProvider",
    "InstallmentMetadata",
    "ProviderErrorCategory",
    "RefreshRequest",
    "RefreshStatus",
    "TransactionStatus",
]

__version__ = "0.1.0"
