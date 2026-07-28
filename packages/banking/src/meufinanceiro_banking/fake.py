"""Deterministic in-memory provider for domain and orchestration tests."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from .models import (
    ConnectionIntent,
    ConnectionIntentKind,
    ConnectionState,
    ConnectionStatus,
    ExternalAccount,
    ExternalCreditCardBill,
    ExternalInvestment,
    ExternalLoan,
    ExternalPage,
    ExternalTransaction,
    RefreshRequest,
    RefreshStatus,
    _clean_identifier,
    _require_aware,
)
from .provider import BankingProviderError, ProviderErrorCategory

_DEFAULT_NOW = datetime(2000, 1, 1, tzinfo=UTC)


def _fixed_clock() -> datetime:
    return _DEFAULT_NOW


class FakeBankingProvider:
    """Configurable fake that performs no network or persistence I/O."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        page_size: int = 100,
    ) -> None:
        if page_size < 1:
            raise ValueError("page_size must be at least one")
        self._clock = clock or _fixed_clock
        self._page_size = page_size
        self._sequence = 0
        self._connections: dict[str, ConnectionState] = {}
        self._residence_by_connection: dict[str, str] = {}
        self._accounts_by_connection: dict[str, tuple[ExternalAccount, ...]] = {}
        self._connection_by_account: dict[str, str] = {}
        self._transactions_by_account: dict[
            str,
            tuple[ExternalTransaction, ...],
        ] = {}
        self._bills_by_account: dict[str, tuple[ExternalCreditCardBill, ...]] = {}
        self._investments_by_connection: dict[
            str,
            tuple[ExternalInvestment, ...],
        ] = {}
        self._loans_by_connection: dict[str, tuple[ExternalLoan, ...]] = {}

    @property
    def provider_name(self) -> str:
        return "fake"

    def seed_connection(
        self,
        state: ConnectionState,
        *,
        residence_id: str,
        accounts: Sequence[ExternalAccount] = (),
        transactions: Sequence[ExternalTransaction] = (),
        bills: Sequence[ExternalCreditCardBill] = (),
        investments: Sequence[ExternalInvestment] = (),
        loans: Sequence[ExternalLoan] = (),
    ) -> None:
        """Replace all fixtures associated with one external connection."""
        connection_id = state.external_connection_id
        normalized_residence_id = _clean_identifier(
            residence_id,
            "residence_id",
        )
        normalized_accounts = tuple(accounts)
        account_ids = {account.external_account_id for account in normalized_accounts}
        if len(account_ids) != len(normalized_accounts):
            raise ValueError("accounts must have unique external_account_id values")
        for account in normalized_accounts:
            if account.external_connection_id != connection_id:
                raise ValueError("account belongs to a different connection")
            owner = self._connection_by_account.get(account.external_account_id)
            if owner is not None and owner != connection_id:
                raise ValueError("account is already assigned to another connection")

        normalized_transactions = tuple(transactions)
        for transaction in normalized_transactions:
            if transaction.external_account_id not in account_ids:
                raise ValueError("transaction belongs to an unknown seeded account")

        normalized_bills = tuple(bills)
        for bill in normalized_bills:
            if bill.external_account_id not in account_ids:
                raise ValueError("bill belongs to an unknown seeded account")

        normalized_investments = tuple(investments)
        for investment in normalized_investments:
            if investment.external_connection_id != connection_id:
                raise ValueError("investment belongs to a different connection")

        normalized_loans = tuple(loans)
        for loan in normalized_loans:
            if loan.external_connection_id != connection_id:
                raise ValueError("loan belongs to a different connection")

        previous_accounts = self._accounts_by_connection.get(connection_id, ())
        for account in previous_accounts:
            self._connection_by_account.pop(account.external_account_id, None)
            self._transactions_by_account.pop(account.external_account_id, None)
            self._bills_by_account.pop(account.external_account_id, None)

        self._connections[connection_id] = state
        self._residence_by_connection[connection_id] = normalized_residence_id
        self._accounts_by_connection[connection_id] = normalized_accounts
        self._investments_by_connection[connection_id] = normalized_investments
        self._loans_by_connection[connection_id] = normalized_loans

        for account in normalized_accounts:
            account_id = account.external_account_id
            self._connection_by_account[account_id] = connection_id
            self._transactions_by_account[account_id] = tuple(
                transaction
                for transaction in normalized_transactions
                if transaction.external_account_id == account_id
            )
            self._bills_by_account[account_id] = tuple(
                bill
                for bill in normalized_bills
                if bill.external_account_id == account_id
            )

    def create_connection_intent(
        self,
        residence_id: str,
        actor_id: str,
    ) -> ConnectionIntent:
        normalized_residence_id = _clean_identifier(
            residence_id,
            "residence_id",
        )
        normalized_actor_id = _clean_identifier(actor_id, "actor_id")
        now = self._now()
        return ConnectionIntent(
            intent_id=self._next_id("intent"),
            kind=ConnectionIntentKind.CONNECT,
            residence_id=normalized_residence_id,
            actor_id=normalized_actor_id,
            expires_at=now + timedelta(minutes=5),
        )

    def create_reauthentication_intent(
        self,
        external_connection_id: str,
        actor_id: str,
    ) -> ConnectionIntent:
        connection = self.get_connection(external_connection_id)
        if connection.status is ConnectionStatus.DISCONNECTED:
            raise BankingProviderError(
                ProviderErrorCategory.CONFLICT,
                retryable=False,
                safe_message="connection is disconnected",
            )
        normalized_actor_id = _clean_identifier(actor_id, "actor_id")
        now = self._now()
        return ConnectionIntent(
            intent_id=self._next_id("reauth"),
            kind=ConnectionIntentKind.REAUTHENTICATE,
            residence_id=self._residence_by_connection[external_connection_id],
            actor_id=normalized_actor_id,
            expires_at=now + timedelta(minutes=5),
            external_connection_id=external_connection_id,
        )

    def get_connection(self, external_connection_id: str) -> ConnectionState:
        connection_id = _clean_identifier(
            external_connection_id,
            "external_connection_id",
        )
        try:
            return self._connections[connection_id]
        except KeyError as error:
            raise BankingProviderError(
                ProviderErrorCategory.NOT_FOUND,
                retryable=False,
                safe_message="connection was not found",
            ) from error

    def get_capabilities(
        self,
        external_connection_id: str,
    ) -> tuple:
        return self.get_connection(external_connection_id).capabilities

    def list_accounts(
        self,
        external_connection_id: str,
    ) -> tuple[ExternalAccount, ...]:
        connection = self.get_connection(external_connection_id)
        return self._accounts_by_connection.get(
            connection.external_connection_id,
            (),
        )

    def list_transactions(
        self,
        external_account_id: str,
        cursor: str | None,
        changed_since: datetime | None,
    ) -> ExternalPage[ExternalTransaction]:
        account_id = self._require_account(external_account_id)
        _require_aware(changed_since, "changed_since")
        records = self._transactions_by_account.get(account_id, ())
        if changed_since is not None:
            records = tuple(
                record
                for record in records
                if record.provider_updated_at is None
                or record.provider_updated_at >= changed_since
            )

        offset = self._parse_cursor(cursor)
        if offset > len(records):
            raise BankingProviderError(
                ProviderErrorCategory.INVALID_REQUEST,
                retryable=False,
                safe_message="cursor is outside the available result set",
            )
        end = min(offset + self._page_size, len(records))
        next_cursor = f"offset:{end}" if end < len(records) else None
        return ExternalPage(
            records=records[offset:end],
            next_cursor=next_cursor,
            source_window=f"offset:{offset}:{end}",
            retrieved_at=self._now(),
        )

    def list_credit_card_bills(
        self,
        external_account_id: str,
    ) -> tuple[ExternalCreditCardBill, ...]:
        account_id = self._require_account(external_account_id)
        return self._bills_by_account.get(account_id, ())

    def list_investments(
        self,
        external_connection_id: str,
    ) -> tuple[ExternalInvestment, ...]:
        connection = self.get_connection(external_connection_id)
        return self._investments_by_connection.get(
            connection.external_connection_id,
            (),
        )

    def list_loans(
        self,
        external_connection_id: str,
    ) -> tuple[ExternalLoan, ...]:
        connection = self.get_connection(external_connection_id)
        return self._loans_by_connection.get(
            connection.external_connection_id,
            (),
        )

    def request_refresh(
        self,
        external_connection_id: str,
        actor_id: str,
    ) -> RefreshRequest:
        connection = self.get_connection(external_connection_id)
        _clean_identifier(actor_id, "actor_id")
        if connection.status is ConnectionStatus.DISCONNECTED:
            raise BankingProviderError(
                ProviderErrorCategory.CONFLICT,
                retryable=False,
                safe_message="connection is disconnected",
            )
        if connection.requires_user_action:
            return RefreshRequest(
                request_id=self._next_id("refresh"),
                external_connection_id=external_connection_id,
                status=RefreshStatus.REQUIRES_USER_ACTION,
                requested_at=self._now(),
            )

        now = self._now()
        next_allowed = connection.next_refresh_allowed_at
        if next_allowed is not None and next_allowed > now:
            return RefreshRequest(
                request_id=self._next_id("refresh"),
                external_connection_id=external_connection_id,
                status=RefreshStatus.RATE_LIMITED,
                requested_at=now,
                next_refresh_allowed_at=next_allowed,
            )
        return RefreshRequest(
            request_id=self._next_id("refresh"),
            external_connection_id=external_connection_id,
            status=RefreshStatus.REQUESTED,
            requested_at=now,
            next_poll_at=now + timedelta(seconds=5),
        )

    def disconnect(self, external_connection_id: str, actor_id: str) -> None:
        connection = self.get_connection(external_connection_id)
        _clean_identifier(actor_id, "actor_id")
        self._connections[external_connection_id] = replace(
            connection,
            status=ConnectionStatus.DISCONNECTED,
            requires_user_action=False,
            provider_reason_code=None,
        )

    def _now(self) -> datetime:
        now = self._clock()
        _require_aware(now, "clock result")
        return now

    def _next_id(self, prefix: str) -> str:
        self._sequence += 1
        return f"fake-{prefix}-{self._sequence:06d}"

    def _require_account(self, external_account_id: str) -> str:
        account_id = _clean_identifier(
            external_account_id,
            "external_account_id",
        )
        if account_id not in self._connection_by_account:
            raise BankingProviderError(
                ProviderErrorCategory.NOT_FOUND,
                retryable=False,
                safe_message="account was not found",
            )
        return account_id

    @staticmethod
    def _parse_cursor(cursor: str | None) -> int:
        if cursor is None:
            return 0
        normalized = _clean_identifier(cursor, "cursor")
        prefix, separator, raw_offset = normalized.partition(":")
        if prefix != "offset" or separator != ":" or not raw_offset.isdigit():
            raise BankingProviderError(
                ProviderErrorCategory.INVALID_REQUEST,
                retryable=False,
                safe_message="cursor is invalid",
            )
        return int(raw_offset)
