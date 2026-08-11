"""Canonical financial domain contracts for MeuFinanceiro."""

from meufinanceiro_finance.access import (
    FinancialAccessDeniedError,
    FinancialActorContext,
    FinancialResourceAudience,
    FinancialVisibilityScope,
    can_access_financial_resource,
    require_financial_resource_access,
)
from meufinanceiro_finance.ids import (
    new_financial_resource_id,
    validate_financial_resource_id,
)
from meufinanceiro_finance.money import (
    CurrencyMismatchError,
    Money,
    RoundingMode,
)

__all__ = [
    "CurrencyMismatchError",
    "FinancialAccessDeniedError",
    "FinancialActorContext",
    "FinancialResourceAudience",
    "FinancialVisibilityScope",
    "Money",
    "RoundingMode",
    "can_access_financial_resource",
    "new_financial_resource_id",
    "require_financial_resource_access",
    "validate_financial_resource_id",
]
