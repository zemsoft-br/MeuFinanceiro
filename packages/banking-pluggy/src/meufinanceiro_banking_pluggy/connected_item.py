"""Strict validation for an Item returned by the Pluggy Connect Widget."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from .gateway import (
    PluggyGatewayError,
    PluggyGatewayErrorCategory,
    PluggyItemSnapshot,
)
from .http_gateway import _PayloadError, _parse_item, _utc_now
from .transport import JsonObject

_MAX_IDENTIFIER_LENGTH = 512
Clock = Callable[[], datetime]


def _identifier(value: object, reason_code: str) -> str:
    if not isinstance(value, str):
        raise _PayloadError(reason_code)
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_IDENTIFIER_LENGTH:
        raise _PayloadError(reason_code)
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise _PayloadError(reason_code)
    return normalized


def parse_connected_item(
    payload: JsonObject,
    *,
    expected_item_id: str,
    expected_client_user_id: str,
    clock: Clock = _utc_now,
) -> PluggyItemSnapshot:
    """Parse one Item and prove it belongs to the expected residence marker."""

    try:
        normalized_expected_item_id = _identifier(
            expected_item_id,
            "INVALID_EXPECTED_ITEM_ID",
        )
        normalized_expected_client_user_id = _identifier(
            expected_client_user_id,
            "INVALID_EXPECTED_CLIENT_USER_ID",
        )
        snapshot = _parse_item(payload, normalized_expected_item_id, clock)
        client_user_id = _identifier(
            payload.get("clientUserId"),
            "INVALID_ITEM_CLIENT_USER_ID",
        )
        if client_user_id != normalized_expected_client_user_id:
            raise PluggyGatewayError(
                PluggyGatewayErrorCategory.AUTHORIZATION,
                retryable=False,
                provider_reason_code="ITEM_OWNERSHIP_MISMATCH",
            )
        return replace(snapshot, client_user_id=client_user_id)
    except PluggyGatewayError:
        raise
    except _PayloadError as error:
        raise PluggyGatewayError(
            PluggyGatewayErrorCategory.INTERNAL,
            retryable=False,
            provider_reason_code=error.reason_code,
        ) from None
