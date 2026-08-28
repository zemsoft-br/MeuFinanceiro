"""Strict read-only Pluggy bill transport and payload normalization."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from .bills import (
    PluggyCreditCardBillSnapshot,
    PluggyCreditCardBillsGateway,
    PluggyCreditCardBillState,
)
from .http_gateway import (
    PluggyGatewayHttpTransport,
    PluggyHttpReadOnlyGateway,
    PluggyPayloadTransport,
    _PayloadError,
    _decimal,
    _effective_date,
    _mapping,
    _optional_text,
    _raise_payload_error,
    _raise_transport_error,
    _required_text,
    _sequence,
    _transport_text,
)
from .transport import JsonObject, PluggyTransportError
from .gateway import PluggyGatewayError, PluggyGatewayErrorCategory

_MAX_IDENTIFIER_LENGTH = 512


@runtime_checkable
class PluggyBillsPayloadTransport(PluggyPayloadTransport, Protocol):
    """JSON transport contract including the account-scoped bills endpoint."""

    def get_bills(self, account_id: str) -> JsonObject: ...


class PluggyBillsGatewayHttpTransport(PluggyGatewayHttpTransport):
    """HTTP transport specialization for `GET /bills?accountId=...`."""

    def get_bills(self, account_id: str) -> JsonObject:
        identifier = _transport_text(
            account_id,
            "account_id",
            max_length=_MAX_IDENTIFIER_LENGTH,
        )
        return self._authenticated_get("bills", params={"accountId": identifier})


def _bill_state(value: object) -> PluggyCreditCardBillState:
    raw = _optional_text(value, "INVALID_BILL_STATUS", max_length=64)
    if raw is None:
        return PluggyCreditCardBillState.UNKNOWN
    try:
        return PluggyCreditCardBillState(raw.upper())
    except ValueError:
        return PluggyCreditCardBillState.UNKNOWN


def _optional_effective_date(value: object, reason_code: str):
    if value is None:
        return None
    return _effective_date(value, reason_code)


def _parse_bill(
    value: object,
    expected_account_id: str,
) -> PluggyCreditCardBillSnapshot:
    record: Mapping[str, object] = _mapping(value, "INVALID_BILL_RECORD")
    minimum_value = record.get("minimumPaymentAmount")
    return PluggyCreditCardBillSnapshot(
        bill_id=_required_text(
            record,
            "id",
            "INVALID_BILL_ID",
            max_length=_MAX_IDENTIFIER_LENGTH,
        ),
        account_id=expected_account_id,
        state=_bill_state(record.get("status")),
        due_date=_effective_date(record.get("dueDate"), "INVALID_BILL_DUE_DATE"),
        close_date=_optional_effective_date(
            record.get("billClosingDate"),
            "INVALID_BILL_CLOSING_DATE",
        ),
        total_amount=_decimal(record.get("totalAmount"), "INVALID_BILL_TOTAL_AMOUNT"),
        minimum_payment=(
            None
            if minimum_value is None
            else _decimal(minimum_value, "INVALID_BILL_MINIMUM_PAYMENT")
        ),
        currency=_required_text(
            record,
            "totalAmountCurrencyCode",
            "INVALID_BILL_CURRENCY",
            max_length=3,
        ),
    )


def _parse_bills(
    payload: JsonObject,
    expected_account_id: str,
) -> tuple[PluggyCreditCardBillSnapshot, ...]:
    try:
        records = _sequence(payload.get("results"), "INVALID_BILLS_COLLECTION")
        parsed = tuple(_parse_bill(record, expected_account_id) for record in records)
        identifiers = [bill.bill_id for bill in parsed]
        if len(identifiers) != len(set(identifiers)):
            raise _PayloadError("DUPLICATE_BILL_ID")
        return parsed
    except _PayloadError:
        raise
    except (TypeError, ValueError, AttributeError):
        raise _PayloadError("INVALID_BILLS_PAYLOAD") from None


class PluggyBillsHttpReadOnlyGateway(
    PluggyHttpReadOnlyGateway,
    PluggyCreditCardBillsGateway,
):
    """Read-only gateway that adds strict credit-card bill normalization."""

    def __init__(self, transport: PluggyBillsPayloadTransport) -> None:
        if not isinstance(transport, PluggyBillsPayloadTransport):
            raise TypeError("transport must satisfy PluggyBillsPayloadTransport")
        super().__init__(transport)
        self._bills_transport = transport

    def list_credit_card_bills(
        self,
        account_id: str,
    ) -> tuple[PluggyCreditCardBillSnapshot, ...]:
        try:
            payload = self._bills_transport.get_bills(account_id)
            return _parse_bills(payload, account_id)
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
                provider_reason_code="UNEXPECTED_BILLS_GATEWAY_FAILURE",
            ) from None


__all__ = [
    "PluggyBillsGatewayHttpTransport",
    "PluggyBillsHttpReadOnlyGateway",
    "PluggyBillsPayloadTransport",
]
