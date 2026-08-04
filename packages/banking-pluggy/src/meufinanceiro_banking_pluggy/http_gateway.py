"""Strict Pluggy payload parsing and concrete read-only HTTP gateway."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol, TypeAlias, cast, runtime_checkable
from urllib.parse import parse_qs, urlsplit

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
from .transport import (
    JsonObject,
    PluggyHttpTransport,
    PluggyTransportError,
    PluggyTransportErrorCategory,
)

Clock: TypeAlias = Callable[[], datetime]

_MAX_TEXT_LENGTH = 512
_MAX_IDENTIFIER_LENGTH = 512
_MAX_CURSOR_LENGTH = 4096
_MAX_RECORDS_PER_PAGE = 1000
_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_-]{0,127}$")

_USER_ACTION_STATUSES = {
    "WAITING_USER_ACTION",
    "WAITING_USER_INPUT",
    "USER_AUTHORIZATION_PENDING",
    "USER_AUTHORIZATION_NOT_GRANTED",
}
_REAUTHENTICATION_STATUSES = {
    "INVALID_CREDENTIALS",
    "LOGIN_ERROR",
    "ACCOUNT_NEEDS_ACTION",
}
_IN_PROGRESS_STATUSES = {
    "CREATED",
    "LOGIN_IN_PROGRESS",
    "UPDATING",
}
_RATE_LIMIT_STATUSES = {
    "BEFORE_ALLOWED_FREQUENCY",
    "RATE_LIMITED",
}


class _PayloadError(ValueError):
    __slots__ = ("reason_code",)

    def __init__(self, reason_code: str) -> None:
        super().__init__("invalid Pluggy payload")
        self.reason_code = reason_code


@runtime_checkable
class PluggyPayloadTransport(Protocol):
    """JSON-only transport contract consumed by the concrete gateway."""

    def get_item(self, item_id: str) -> JsonObject: ...

    def get_accounts(self, item_id: str) -> JsonObject: ...

    def get_transactions_page(
        self,
        account_id: str,
        *,
        after: str | None,
        created_at_from: datetime | None,
    ) -> JsonObject: ...


class PluggyGatewayHttpTransport(PluggyHttpTransport):
    """HTTP transport specialization using Pluggy's current cursor contract."""

    def get_transactions_page(
        self,
        account_id: str,
        *,
        after: str | None,
        created_at_from: datetime | None,
    ) -> JsonObject:
        identifier = _transport_text(
            account_id,
            "account_id",
            max_length=_MAX_IDENTIFIER_LENGTH,
        )
        cursor = _transport_optional_text(
            after,
            "after",
            max_length=_MAX_CURSOR_LENGTH,
        )
        params = {"accountId": identifier}
        if cursor is not None:
            params["after"] = cursor
        if created_at_from is not None:
            if (
                not isinstance(created_at_from, datetime)
                or created_at_from.tzinfo is None
                or created_at_from.utcoffset() is None
            ):
                raise ValueError("created_at_from must be timezone-aware")
            normalized = created_at_from.astimezone(UTC)
            params["createdAtFrom"] = (
                normalized.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            )
        return self._authenticated_get("v2/transactions", params=params)


def _transport_text(value: str, field_name: str, *, max_length: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        raise ValueError(f"{field_name} is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ValueError(f"{field_name} contains control characters")
    return normalized


def _transport_optional_text(
    value: str | None,
    field_name: str,
    *,
    max_length: int,
) -> str | None:
    if value is None:
        return None
    return _transport_text(value, field_name, max_length=max_length)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _mapping(value: object, reason_code: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise _PayloadError(reason_code)
    return cast(Mapping[str, object], value)


def _sequence(value: object, reason_code: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise _PayloadError(reason_code)
    if len(value) > _MAX_RECORDS_PER_PAGE:
        raise _PayloadError(reason_code)
    return cast(Sequence[object], value)


def _text(
    value: object,
    reason_code: str,
    *,
    max_length: int = _MAX_TEXT_LENGTH,
) -> str:
    if not isinstance(value, str):
        raise _PayloadError(reason_code)
    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        raise _PayloadError(reason_code)
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise _PayloadError(reason_code)
    return normalized


def _required_text(
    payload: Mapping[str, object],
    key: str,
    reason_code: str,
    *,
    max_length: int = _MAX_TEXT_LENGTH,
) -> str:
    return _text(payload.get(key), reason_code, max_length=max_length)


def _optional_text(
    value: object,
    reason_code: str,
    *,
    max_length: int = _MAX_TEXT_LENGTH,
) -> str | None:
    if value is None:
        return None
    return _text(value, reason_code, max_length=max_length)


def _safe_reason_code(value: object, fallback: str) -> str:
    if isinstance(value, str):
        normalized = value.strip().upper()
        if _SAFE_CODE.fullmatch(normalized):
            return normalized
    return fallback


def _optional_datetime(value: object, reason_code: str) -> datetime | None:
    if value is None:
        return None
    raw = _text(value, reason_code, max_length=64)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise _PayloadError(reason_code) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _PayloadError(reason_code)
    return parsed.astimezone(UTC)


def _effective_date(value: object, reason_code: str) -> date:
    raw = _text(value, reason_code, max_length=64)
    if len(raw) == 10:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            raise _PayloadError(reason_code) from None
    parsed = _optional_datetime(raw, reason_code)
    if parsed is None:
        raise _PayloadError(reason_code)
    return parsed.date()


def _decimal(value: object, reason_code: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise _PayloadError(reason_code)
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        raise _PayloadError(reason_code) from None
    if not parsed.is_finite():
        raise _PayloadError(reason_code)
    return parsed


def _positive_integer(value: object, reason_code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _PayloadError(reason_code)
    return value


def _item_phase(status: str, execution_status: str | None) -> PluggyConnectionPhase:
    status_code = status.upper()
    execution_code = execution_status.upper() if execution_status is not None else None
    if status_code in _USER_ACTION_STATUSES or execution_code in _USER_ACTION_STATUSES:
        return PluggyConnectionPhase.USER_ACTION_REQUIRED
    if (
        status_code in _REAUTHENTICATION_STATUSES
        or execution_code in _REAUTHENTICATION_STATUSES
    ):
        return PluggyConnectionPhase.REAUTHENTICATION_REQUIRED
    if status_code in _RATE_LIMIT_STATUSES or execution_code in _RATE_LIMIT_STATUSES:
        return PluggyConnectionPhase.RATE_LIMITED
    if status_code in _IN_PROGRESS_STATUSES or execution_code in _IN_PROGRESS_STATUSES:
        return PluggyConnectionPhase.SYNCING
    if status_code == "UPDATED" and execution_code == "PARTIAL_SUCCESS":
        return PluggyConnectionPhase.PARTIAL
    if status_code == "UPDATED" and execution_code in {None, "SUCCESS"}:
        return PluggyConnectionPhase.AVAILABLE
    if status_code == "OUTDATED":
        return PluggyConnectionPhase.TEMPORARILY_UNAVAILABLE
    if status_code in {"DELETED", "DISCONNECTED"}:
        return PluggyConnectionPhase.DISCONNECTED
    return PluggyConnectionPhase.FAILED


def _item_reason_code(payload: Mapping[str, object], status: str) -> str:
    execution = payload.get("executionStatus")
    if execution is not None:
        return _safe_reason_code(execution, "UNRECOGNIZED_EXECUTION_STATUS")
    error = payload.get("error")
    if isinstance(error, dict):
        code = cast(dict[object, object], error).get("code")
        if code is not None:
            return _safe_reason_code(code, "UNRECOGNIZED_ITEM_ERROR")
    return _safe_reason_code(status, "UNRECOGNIZED_ITEM_STATUS")


def _capabilities(
    payload: Mapping[str, object],
    observed_at: datetime,
) -> tuple[PluggyCapabilitySnapshot, ...]:
    connector_value = payload.get("connector")
    products: set[str] | None = None
    if connector_value is not None:
        connector = _mapping(connector_value, "INVALID_ITEM_CONNECTOR")
        raw_products = connector.get("products")
        if raw_products is not None:
            product_values = _sequence(raw_products, "INVALID_ITEM_PRODUCTS")
            products = {
                _text(value, "INVALID_ITEM_PRODUCT", max_length=64).upper()
                for value in product_values
            }

    def snapshot(
        capability: PluggyCapability,
        availability: PluggyCapabilityAvailability,
        reason_code: str | None = None,
    ) -> PluggyCapabilitySnapshot:
        return PluggyCapabilitySnapshot(
            capability=capability,
            availability=availability,
            observed_at=observed_at,
            evidence=PluggyCapabilityEvidence.CONTRACT,
            provider_reason_code=reason_code,
        )

    if products is None:
        return tuple(
            snapshot(capability, PluggyCapabilityAvailability.UNKNOWN)
            for capability in PluggyCapability
        )

    account_availability = (
        PluggyCapabilityAvailability.UNKNOWN
        if "ACCOUNTS" in products
        else PluggyCapabilityAvailability.UNAVAILABLE
    )
    account_reason = "ACCOUNT_TYPE_NOT_OBSERVED" if "ACCOUNTS" in products else None
    return (
        snapshot(
            PluggyCapability.IDENTITY,
            PluggyCapabilityAvailability.AVAILABLE
            if "IDENTITY" in products
            else PluggyCapabilityAvailability.UNAVAILABLE,
        ),
        snapshot(
            PluggyCapability.BANK_ACCOUNTS,
            account_availability,
            account_reason,
        ),
        snapshot(
            PluggyCapability.CREDIT_ACCOUNTS,
            account_availability,
            account_reason,
        ),
        snapshot(
            PluggyCapability.TRANSACTIONS,
            PluggyCapabilityAvailability.AVAILABLE
            if "TRANSACTIONS" in products
            else PluggyCapabilityAvailability.UNAVAILABLE,
        ),
    )


def _parse_item(
    payload: JsonObject,
    expected_item_id: str,
    clock: Clock,
) -> PluggyItemSnapshot:
    try:
        item_id = _required_text(
            payload,
            "id",
            "INVALID_ITEM_ID",
            max_length=_MAX_IDENTIFIER_LENGTH,
        )
        if item_id != expected_item_id:
            raise _PayloadError("ITEM_ASSOCIATION_MISMATCH")
        status = _required_text(payload, "status", "INVALID_ITEM_STATUS", max_length=64)
        execution = _optional_text(
            payload.get("executionStatus"),
            "INVALID_EXECUTION_STATUS",
            max_length=128,
        )
        updated_at = _optional_datetime(payload.get("updatedAt"), "INVALID_UPDATED_AT")
        last_updated = _optional_datetime(
            payload.get("lastUpdatedAt"),
            "INVALID_LAST_UPDATED_AT",
        )
        consent_expires = _optional_datetime(
            payload.get("consentExpiresAt"),
            "INVALID_CONSENT_EXPIRES_AT",
        )
        observed_at = updated_at or last_updated or clock()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise _PayloadError("INVALID_GATEWAY_CLOCK")
        phase = _item_phase(status, execution)
        return PluggyItemSnapshot(
            item_id=item_id,
            phase=phase,
            capabilities=_capabilities(payload, observed_at.astimezone(UTC)),
            last_successful_update_at=last_updated,
            last_attempt_at=updated_at,
            next_refresh_allowed_at=None,
            consent_expires_at=consent_expires,
            provider_reason_code=_item_reason_code(payload, status),
        )
    except _PayloadError:
        raise
    except (TypeError, ValueError, AttributeError):
        raise _PayloadError("INVALID_ITEM_PAYLOAD") from None


def _account_kind(value: str) -> PluggyAccountKind:
    normalized = value.upper()
    if normalized == "BANK":
        return PluggyAccountKind.BANK
    if normalized == "CREDIT":
        return PluggyAccountKind.CREDIT
    return PluggyAccountKind.OTHER


def _number_mask(value: object) -> str | None:
    if value is None:
        return None
    raw = _text(value, "INVALID_ACCOUNT_NUMBER", max_length=128)
    characters = "".join(character for character in raw if character.isalnum())
    if not characters:
        return None
    return f"***{characters[-4:]}"


def _parse_account(
    value: object,
    expected_item_id: str,
) -> PluggyAccountSnapshot:
    record = _mapping(value, "INVALID_ACCOUNT_RECORD")
    account_id = _required_text(
        record,
        "id",
        "INVALID_ACCOUNT_ID",
        max_length=_MAX_IDENTIFIER_LENGTH,
    )
    item_id = _required_text(
        record,
        "itemId",
        "INVALID_ACCOUNT_ITEM_ID",
        max_length=_MAX_IDENTIFIER_LENGTH,
    )
    if item_id != expected_item_id:
        raise _PayloadError("ACCOUNT_ASSOCIATION_MISMATCH")
    account_type = _required_text(
        record,
        "type",
        "INVALID_ACCOUNT_TYPE",
        max_length=64,
    )
    return PluggyAccountSnapshot(
        account_id=account_id,
        item_id=item_id,
        kind=_account_kind(account_type),
        subtype=_required_text(
            record,
            "subtype",
            "INVALID_ACCOUNT_SUBTYPE",
            max_length=128,
        ),
        currency=_required_text(
            record,
            "currencyCode",
            "INVALID_ACCOUNT_CURRENCY",
            max_length=3,
        ),
        name=_optional_text(record.get("name"), "INVALID_ACCOUNT_NAME"),
        number_mask=_number_mask(record.get("number")),
    )


def _parse_accounts(
    payload: JsonObject,
    expected_item_id: str,
) -> tuple[PluggyAccountSnapshot, ...]:
    try:
        records = _sequence(payload.get("results"), "INVALID_ACCOUNTS_COLLECTION")
        parsed = tuple(_parse_account(record, expected_item_id) for record in records)
        identifiers = [account.account_id for account in parsed]
        if len(identifiers) != len(set(identifiers)):
            raise _PayloadError("DUPLICATE_ACCOUNT_ID")
        return parsed
    except _PayloadError:
        raise
    except (TypeError, ValueError, AttributeError):
        raise _PayloadError("INVALID_ACCOUNTS_PAYLOAD") from None


def _installment(
    metadata: Mapping[str, object],
) -> PluggyInstallmentSnapshot | None:
    number_value = metadata.get("installmentNumber")
    count_value = metadata.get("totalInstallments")
    total_value = metadata.get("totalAmount")
    if number_value is None and count_value is None and total_value is None:
        return None
    if number_value is None or count_value is None:
        raise _PayloadError("INCOMPLETE_INSTALLMENT_METADATA")
    return PluggyInstallmentSnapshot(
        number=_positive_integer(number_value, "INVALID_INSTALLMENT_NUMBER"),
        count=_positive_integer(count_value, "INVALID_INSTALLMENT_COUNT"),
        total_amount=(
            None
            if total_value is None
            else _decimal(total_value, "INVALID_INSTALLMENT_TOTAL")
        ),
    )


def _parse_transaction(
    value: object,
    expected_account_id: str,
) -> PluggyTransactionSnapshot:
    record = _mapping(value, "INVALID_TRANSACTION_RECORD")
    account_id = _required_text(
        record,
        "accountId",
        "INVALID_TRANSACTION_ACCOUNT_ID",
        max_length=_MAX_IDENTIFIER_LENGTH,
    )
    if account_id != expected_account_id:
        raise _PayloadError("TRANSACTION_ASSOCIATION_MISMATCH")
    status = _required_text(
        record,
        "status",
        "INVALID_TRANSACTION_STATUS",
        max_length=32,
    ).upper()
    try:
        state = PluggyTransactionState(status)
    except ValueError:
        raise _PayloadError("UNSUPPORTED_TRANSACTION_STATUS") from None
    metadata_value = record.get("creditCardMetadata")
    metadata = (
        None
        if metadata_value is None
        else _mapping(metadata_value, "INVALID_CREDIT_CARD_METADATA")
    )
    return PluggyTransactionSnapshot(
        account_id=account_id,
        state=state,
        effective_date=_effective_date(record.get("date"), "INVALID_TRANSACTION_DATE"),
        amount=_decimal(record.get("amount"), "INVALID_TRANSACTION_AMOUNT"),
        currency=_required_text(
            record,
            "currencyCode",
            "INVALID_TRANSACTION_CURRENCY",
            max_length=3,
        ),
        transaction_id=_optional_text(
            record.get("id"),
            "INVALID_TRANSACTION_ID",
            max_length=_MAX_IDENTIFIER_LENGTH,
        ),
        updated_at=_optional_datetime(
            record.get("updatedAt"),
            "INVALID_TRANSACTION_UPDATED_AT",
        ),
        description=_optional_text(
            record.get("description"),
            "INVALID_TRANSACTION_DESCRIPTION",
        ),
        category=_optional_text(
            record.get("category"),
            "INVALID_TRANSACTION_CATEGORY",
        ),
        bill_reference=(
            None
            if metadata is None
            else _optional_text(
                metadata.get("billId"),
                "INVALID_BILL_REFERENCE",
                max_length=_MAX_IDENTIFIER_LENGTH,
            )
        ),
        installment=None if metadata is None else _installment(metadata),
    )


def _next_cursor(value: object, expected_account_id: str) -> str | None:
    if value is None:
        return None
    raw = _text(value, "INVALID_NEXT_CURSOR", max_length=8192)
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise _PayloadError("UNSAFE_NEXT_CURSOR")
    if parsed.path not in {"", "/v2/transactions", "v2/transactions"}:
        raise _PayloadError("UNSAFE_NEXT_CURSOR_PATH")
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    if set(query) != {"accountId", "after"}:
        raise _PayloadError("UNEXPECTED_NEXT_CURSOR_FIELDS")
    if query.get("accountId") != [expected_account_id]:
        raise _PayloadError("NEXT_CURSOR_ACCOUNT_MISMATCH")
    after_values = query.get("after")
    if after_values is None or len(after_values) != 1:
        raise _PayloadError("AMBIGUOUS_NEXT_CURSOR")
    return _text(
        after_values[0],
        "INVALID_NEXT_CURSOR_VALUE",
        max_length=_MAX_CURSOR_LENGTH,
    )


def _parse_transactions(
    payload: JsonObject,
    expected_account_id: str,
    changed_since: datetime | None,
    clock: Clock,
) -> PluggyTransactionPageSnapshot:
    try:
        records = _sequence(
            payload.get("results"),
            "INVALID_TRANSACTIONS_COLLECTION",
        )
        parsed = tuple(
            _parse_transaction(record, expected_account_id) for record in records
        )
        identifiers = [
            transaction.transaction_id
            for transaction in parsed
            if transaction.transaction_id is not None
        ]
        if len(identifiers) != len(set(identifiers)):
            raise _PayloadError("DUPLICATE_TRANSACTION_ID")
        retrieved_at = clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise _PayloadError("INVALID_GATEWAY_CLOCK")
        return PluggyTransactionPageSnapshot(
            records=parsed,
            next_cursor=_next_cursor(payload.get("next"), expected_account_id),
            source_window=(
                "CREATED_AT_FROM" if changed_since is not None else "FULL"
            ),
            retrieved_at=retrieved_at.astimezone(UTC),
        )
    except _PayloadError:
        raise
    except (TypeError, ValueError, AttributeError):
        raise _PayloadError("INVALID_TRANSACTIONS_PAYLOAD") from None


_TRANSPORT_CATEGORIES = {
    PluggyTransportErrorCategory.AUTHENTICATION: (
        PluggyGatewayErrorCategory.AUTHENTICATION
    ),
    PluggyTransportErrorCategory.AUTHORIZATION: (
        PluggyGatewayErrorCategory.AUTHORIZATION
    ),
    PluggyTransportErrorCategory.NOT_FOUND: PluggyGatewayErrorCategory.NOT_FOUND,
    PluggyTransportErrorCategory.INVALID_REQUEST: (
        PluggyGatewayErrorCategory.INVALID_REQUEST
    ),
    PluggyTransportErrorCategory.RATE_LIMITED: (
        PluggyGatewayErrorCategory.RATE_LIMITED
    ),
    PluggyTransportErrorCategory.TEMPORARILY_UNAVAILABLE: (
        PluggyGatewayErrorCategory.TEMPORARILY_UNAVAILABLE
    ),
    PluggyTransportErrorCategory.INVALID_RESPONSE: PluggyGatewayErrorCategory.INTERNAL,
    PluggyTransportErrorCategory.INTERNAL: PluggyGatewayErrorCategory.INTERNAL,
}


def _raise_transport_error(error: PluggyTransportError) -> None:
    category = _TRANSPORT_CATEGORIES.get(
        error.category,
        PluggyGatewayErrorCategory.INTERNAL,
    )
    raise PluggyGatewayError(
        category,
        retryable=error.retryable,
        provider_reason_code=error.provider_reason_code,
    ) from None


def _raise_payload_error(error: _PayloadError) -> None:
    raise PluggyGatewayError(
        PluggyGatewayErrorCategory.INTERNAL,
        retryable=False,
        provider_reason_code=error.reason_code,
    ) from None


class PluggyHttpReadOnlyGateway(PluggyReadOnlyGateway):
    """Concrete JSON-to-snapshot gateway with no raw payload escape hatch."""

    def __init__(
        self,
        transport: PluggyPayloadTransport,
        *,
        clock: Clock = _utc_now,
    ) -> None:
        if not isinstance(transport, PluggyPayloadTransport):
            raise TypeError("transport must satisfy PluggyPayloadTransport")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._transport = transport
        self._clock = clock

    def get_item(self, item_id: str) -> PluggyItemSnapshot:
        try:
            payload = self._transport.get_item(item_id)
            return _parse_item(payload, item_id, self._clock)
        except PluggyTransportError as error:
            _raise_transport_error(error)
        except _PayloadError as error:
            _raise_payload_error(error)
        except PluggyGatewayError:
            raise
        except Exception:
            raise PluggyGatewayError(
                PluggyGatewayErrorCategory.INTERNAL,
                retryable=False,
                provider_reason_code="UNEXPECTED_ITEM_GATEWAY_FAILURE",
            ) from None

    def get_accounts(self, item_id: str) -> tuple[PluggyAccountSnapshot, ...]:
        try:
            payload = self._transport.get_accounts(item_id)
            return _parse_accounts(payload, item_id)
        except PluggyTransportError as error:
            _raise_transport_error(error)
        except _PayloadError as error:
            _raise_payload_error(error)
        except PluggyGatewayError:
            raise
        except Exception:
            raise PluggyGatewayError(
                PluggyGatewayErrorCategory.INTERNAL,
                retryable=False,
                provider_reason_code="UNEXPECTED_ACCOUNTS_GATEWAY_FAILURE",
            ) from None

    def list_accounts(self, item_id: str) -> tuple[PluggyAccountSnapshot, ...]:
        return self.get_accounts(item_id)

    def list_transactions(
        self,
        account_id: str,
        cursor: str | None,
        changed_since: datetime | None,
    ) -> PluggyTransactionPageSnapshot:
        if changed_since is not None and (
            not isinstance(changed_since, datetime)
            or changed_since.tzinfo is None
            or changed_since.utcoffset() is None
        ):
            raise PluggyGatewayError(
                PluggyGatewayErrorCategory.INVALID_REQUEST,
                retryable=False,
                provider_reason_code="CHANGED_SINCE_MUST_BE_AWARE",
            )
        try:
            payload = self._transport.get_transactions_page(
                account_id,
                after=cursor,
                created_at_from=changed_since,
            )
            return _parse_transactions(
                payload,
                account_id,
                changed_since,
                self._clock,
            )
        except PluggyTransportError as error:
            _raise_transport_error(error)
        except _PayloadError as error:
            _raise_payload_error(error)
        except PluggyGatewayError:
            raise
        except Exception:
            raise PluggyGatewayError(
                PluggyGatewayErrorCategory.INTERNAL,
                retryable=False,
                provider_reason_code="UNEXPECTED_TRANSACTIONS_GATEWAY_FAILURE",
            ) from None
