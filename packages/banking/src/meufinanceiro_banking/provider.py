"""Executable provider-neutral banking boundary."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from .models import (
    ConnectionCapability,
    ConnectionIntent,
    ConnectionState,
    ExternalAccount,
    ExternalCreditCardBill,
    ExternalInvestment,
    ExternalLoan,
    ExternalPage,
    ExternalTransaction,
    RefreshRequest,
    _clean_optional_text,
)


class ProviderErrorCategory(StrEnum):
    """Sanitized categories exposed by provider adapters."""

    AUTHENTICATION = "AUTHENTICATION"
    AUTHORIZATION = "AUTHORIZATION"
    NOT_FOUND = "NOT_FOUND"
    INVALID_REQUEST = "INVALID_REQUEST"
    REQUIRES_USER_ACTION = "REQUIRES_USER_ACTION"
    RATE_LIMITED = "RATE_LIMITED"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    CONFLICT = "CONFLICT"
    UNSUPPORTED = "UNSUPPORTED"
    INTERNAL = "INTERNAL"


class BankingProviderError(RuntimeError):
    """Sanitized error that never carries raw responses or credentials."""

    __slots__ = ("category", "provider_reason_code", "retryable")

    def __init__(
        self,
        category: ProviderErrorCategory,
        *,
        retryable: bool,
        provider_reason_code: str | None = None,
        safe_message: str | None = None,
    ) -> None:
        reason = _clean_optional_text(
            provider_reason_code,
            "provider_reason_code",
            max_length=128,
        )
        message = _clean_optional_text(
            safe_message,
            "safe_message",
            max_length=256,
        )
        super().__init__(message or category.value)
        self.category = category
        self.retryable = retryable
        self.provider_reason_code = reason


@runtime_checkable
class BankingProvider(Protocol):
    """Structural contract implemented by every banking adapter."""

    @property
    def provider_name(self) -> str:
        """Return the stable neutral provider slug."""
        ...

    def create_connection_intent(
        self,
        residence_id: str,
        actor_id: str,
    ) -> ConnectionIntent:
        """Create a short-lived intent without exposing provider tokens."""
        ...

    def create_reauthentication_intent(
        self,
        external_connection_id: str,
        actor_id: str,
    ) -> ConnectionIntent:
        """Create a short-lived intent for an existing connection."""
        ...

    def get_connection(self, external_connection_id: str) -> ConnectionState:
        """Return one normalized connection snapshot."""
        ...

    def get_capabilities(
        self,
        external_connection_id: str,
    ) -> tuple[ConnectionCapability, ...]:
        """Return the capabilities observed for one connection."""
        ...

    def list_accounts(
        self,
        external_connection_id: str,
    ) -> tuple[ExternalAccount, ...]:
        """Return normalized accounts for one connection."""
        ...

    def list_transactions(
        self,
        external_account_id: str,
        cursor: str | None,
        changed_since: datetime | None,
    ) -> ExternalPage[ExternalTransaction]:
        """Return one cursor page of normalized transactions."""
        ...

    def list_credit_card_bills(
        self,
        external_account_id: str,
    ) -> tuple[ExternalCreditCardBill, ...]:
        """Return normalized bills for one credit account."""
        ...

    def list_investments(
        self,
        external_connection_id: str,
    ) -> tuple[ExternalInvestment, ...]:
        """Return normalized investments for one connection."""
        ...

    def list_loans(
        self,
        external_connection_id: str,
    ) -> tuple[ExternalLoan, ...]:
        """Return normalized loans for one connection."""
        ...

    def request_refresh(
        self,
        external_connection_id: str,
        actor_id: str,
    ) -> RefreshRequest:
        """Request a bounded manual refresh."""
        ...

    def disconnect(self, external_connection_id: str, actor_id: str) -> None:
        """Disconnect explicitly without deleting local history."""
        ...
