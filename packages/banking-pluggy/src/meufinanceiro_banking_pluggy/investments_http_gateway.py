"""Strict read-only Pluggy investment pagination and payload normalization."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from .gateway import PluggyGatewayError, PluggyGatewayErrorCategory
from .http_gateway import (
    PluggyGatewayHttpTransport,
    PluggyHttpReadOnlyGateway,
    PluggyPayloadTransport,
    _PayloadError,
    _decimal,
    _mapping,
    _optional_datetime,
    _raise_payload_error,
    _raise_transport_error,
    _required_text,
    _sequence,
    _transport_text,
)
from .investments import PluggyInvestmentSnapshot
from .transport import JsonObject, PluggyTransportError

_MAX_IDENTIFIER_LENGTH = 512
_PAGE_SIZE = 500
_DEFAULT_MAX_PAGES = 20
_DEFAULT_MAX_RECORDS = 10_000


@runtime_checkable
class PluggyInvestmentsPayloadTransport(PluggyPayloadTransport, Protocol):
    """JSON transport contract including paged investment reads."""

    def get_investments_page(
        self,
        item_id: str,
        *,
        page: int,
        page_size: int,
    ) -> JsonObject: ...


class PluggyInvestmentsGatewayHttpTransport(PluggyGatewayHttpTransport):
    """HTTP transport specialization for GET /investments by Item."""

    def get_investments_page(
        self,
        item_id: str,
        *,
        page: int,
        page_size: int,
    ) -> JsonObject:
        identifier = _transport_text(
            item_id,
            "item_id",
            max_length=_MAX_IDENTIFIER_LENGTH,
        )
        if isinstance(page, bool) or not isinstance(page, int) or page < 0:
            raise ValueError("page must be a non-negative integer")
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or not 1 <= page_size <= _PAGE_SIZE
        ):
            raise ValueError("page_size is outside the supported range")
        return self._authenticated_get(
            "investments",
            params={
                "itemId": identifier,
                "page": str(page),
                "pageSize": str(page_size),
            },
        )


def _non_negative_integer(value: object, reason_code: str) -> int:
    if isinstance(value, bool):
        raise _PayloadError(reason_code)
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float) and value.is_integer():
        parsed = int(value)
    else:
        raise _PayloadError(reason_code)
    if parsed < 0:
        raise _PayloadError(reason_code)
    return parsed


def _parse_investment(
    value: object,
    expected_item_id: str,
) -> PluggyInvestmentSnapshot:
    record: Mapping[str, object] = _mapping(value, "INVALID_INVESTMENT_RECORD")
    item_id = _required_text(
        record,
        "itemId",
        "INVALID_INVESTMENT_ITEM_ID",
        max_length=_MAX_IDENTIFIER_LENGTH,
    )
    if item_id != expected_item_id:
        raise _PayloadError("INVESTMENT_ASSOCIATION_MISMATCH")
    balance = _decimal(record.get("balance"), "INVALID_INVESTMENT_BALANCE")
    if balance < 0:
        raise _PayloadError("INVALID_INVESTMENT_BALANCE")
    as_of = _optional_datetime(record.get("date"), "INVALID_INVESTMENT_DATE")
    if as_of is None:
        raise _PayloadError("MISSING_INVESTMENT_DATE")
    return PluggyInvestmentSnapshot(
        investment_id=_required_text(
            record,
            "id",
            "INVALID_INVESTMENT_ID",
            max_length=_MAX_IDENTIFIER_LENGTH,
        ),
        item_id=item_id,
        name=_required_text(record, "name", "INVALID_INVESTMENT_NAME"),
        kind=_required_text(
            record,
            "type",
            "INVALID_INVESTMENT_TYPE",
            max_length=128,
        ),
        balance=balance,
        currency=_required_text(
            record,
            "currencyCode",
            "INVALID_INVESTMENT_CURRENCY",
            max_length=3,
        ),
        as_of=as_of,
    )


def _parse_page(
    payload: JsonObject,
    expected_item_id: str,
) -> tuple[int, int, int, tuple[PluggyInvestmentSnapshot, ...]]:
    try:
        page = _non_negative_integer(payload.get("page"), "INVALID_INVESTMENT_PAGE")
        total = _non_negative_integer(payload.get("total"), "INVALID_INVESTMENT_TOTAL")
        total_pages = _non_negative_integer(
            payload.get("totalPages"),
            "INVALID_INVESTMENT_TOTAL_PAGES",
        )
        records = _sequence(
            payload.get("results"),
            "INVALID_INVESTMENTS_COLLECTION",
        )
        parsed = tuple(_parse_investment(record, expected_item_id) for record in records)
        if total_pages == 0:
            if page != 0 or total != 0 or parsed:
                raise _PayloadError("INCONSISTENT_INVESTMENT_PAGINATION")
        elif page >= total_pages:
            raise _PayloadError("INCONSISTENT_INVESTMENT_PAGINATION")
        return page, total, total_pages, parsed
    except _PayloadError:
        raise
    except (TypeError, ValueError, AttributeError):
        raise _PayloadError("INVALID_INVESTMENTS_PAYLOAD") from None


class PluggyInvestmentsHttpReadOnlyGateway(PluggyHttpReadOnlyGateway):
    """Read-only gateway that normalizes bounded investment pages."""

    def __init__(
        self,
        transport: PluggyInvestmentsPayloadTransport,
        *,
        max_pages: int = _DEFAULT_MAX_PAGES,
        max_records: int = _DEFAULT_MAX_RECORDS,
    ) -> None:
        if not isinstance(transport, PluggyInvestmentsPayloadTransport):
            raise TypeError("transport must satisfy PluggyInvestmentsPayloadTransport")
        if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1:
            raise ValueError("max_pages must be a positive integer")
        if (
            isinstance(max_records, bool)
            or not isinstance(max_records, int)
            or max_records < 1
        ):
            raise ValueError("max_records must be a positive integer")
        super().__init__(transport)
        self._investments_transport = transport
        self._max_pages = max_pages
        self._max_records = max_records

    def list_investments(
        self,
        item_id: str,
    ) -> tuple[PluggyInvestmentSnapshot, ...]:
        try:
            page_index = 0
            expected_total: int | None = None
            expected_total_pages: int | None = None
            records: list[PluggyInvestmentSnapshot] = []
            identifiers: set[str] = set()

            while True:
                if page_index >= self._max_pages:
                    raise _PayloadError("INVESTMENT_PAGE_LIMIT_EXCEEDED")
                payload = self._investments_transport.get_investments_page(
                    item_id,
                    page=page_index,
                    page_size=_PAGE_SIZE,
                )
                page, total, total_pages, page_records = _parse_page(payload, item_id)
                if page != page_index:
                    raise _PayloadError("INVESTMENT_PAGE_MISMATCH")

                if expected_total is None:
                    expected_total = total
                    expected_total_pages = total_pages
                    if total > self._max_records:
                        raise _PayloadError("INVESTMENT_RECORD_LIMIT_EXCEEDED")
                    if total_pages > self._max_pages:
                        raise _PayloadError("INVESTMENT_PAGE_LIMIT_EXCEEDED")
                elif total != expected_total or total_pages != expected_total_pages:
                    raise _PayloadError("INCONSISTENT_INVESTMENT_PAGINATION")

                for record in page_records:
                    if record.investment_id in identifiers:
                        raise _PayloadError("DUPLICATE_INVESTMENT_ID")
                    identifiers.add(record.investment_id)
                    records.append(record)
                    if len(records) > self._max_records:
                        raise _PayloadError("INVESTMENT_RECORD_LIMIT_EXCEEDED")

                if total_pages == 0:
                    return ()
                if page_index + 1 >= total_pages:
                    if expected_total is None or len(records) != expected_total:
                        raise _PayloadError("INCOMPLETE_INVESTMENT_COLLECTION")
                    return tuple(records)
                page_index += 1
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
                provider_reason_code="UNEXPECTED_INVESTMENTS_GATEWAY_FAILURE",
            ) from None


__all__ = [
    "PluggyInvestmentsGatewayHttpTransport",
    "PluggyInvestmentsHttpReadOnlyGateway",
    "PluggyInvestmentsPayloadTransport",
]
