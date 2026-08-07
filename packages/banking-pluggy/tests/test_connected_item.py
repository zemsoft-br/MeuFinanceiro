from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from meufinanceiro_banking_pluggy import (
    PluggyConnectionPhase,
    PluggyGatewayError,
    PluggyGatewayErrorCategory,
    parse_connected_item,
)

RESIDENCE_ID = UUID("20000000-0000-4000-8000-000000000002")
ITEM_ID = "synthetic-item-123"
CLIENT_USER_ID = f"residence:{RESIDENCE_ID}"
NOW = datetime(2026, 8, 7, tzinfo=UTC)


def item_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": ITEM_ID,
        "clientUserId": CLIENT_USER_ID,
        "status": "UPDATED",
        "executionStatus": "SUCCESS",
        "updatedAt": "2026-08-07T00:00:00Z",
        "lastUpdatedAt": "2026-08-07T00:00:00Z",
        "connector": {"products": ["ACCOUNTS", "TRANSACTIONS"]},
    }
    payload.update(overrides)
    return payload


def test_connected_item_requires_exact_ownership_marker() -> None:
    snapshot = parse_connected_item(
        item_payload(),
        expected_item_id=ITEM_ID,
        expected_client_user_id=CLIENT_USER_ID,
        clock=lambda: NOW,
    )

    assert snapshot.item_id == ITEM_ID
    assert snapshot.client_user_id == CLIENT_USER_ID
    assert snapshot.phase is PluggyConnectionPhase.AVAILABLE
    assert len(snapshot.capabilities) == 4


def test_connected_item_rejects_provider_item_mismatch_without_leaking_ids() -> None:
    provider_item_id = "different-provider-item"

    with pytest.raises(PluggyGatewayError) as captured:
        parse_connected_item(
            item_payload(id=provider_item_id),
            expected_item_id=ITEM_ID,
            expected_client_user_id=CLIENT_USER_ID,
            clock=lambda: NOW,
        )

    assert captured.value.category is PluggyGatewayErrorCategory.INTERNAL
    assert captured.value.provider_reason_code == "ITEM_ASSOCIATION_MISMATCH"
    assert ITEM_ID not in str(captured.value)
    assert provider_item_id not in str(captured.value)
    assert captured.value.__cause__ is None


def test_connected_item_rejects_missing_ownership_marker_fail_closed() -> None:
    payload = item_payload()
    payload.pop("clientUserId")

    with pytest.raises(PluggyGatewayError) as captured:
        parse_connected_item(
            payload,
            expected_item_id=ITEM_ID,
            expected_client_user_id=CLIENT_USER_ID,
            clock=lambda: NOW,
        )

    assert captured.value.category is PluggyGatewayErrorCategory.INTERNAL
    assert captured.value.provider_reason_code == "INVALID_ITEM_CLIENT_USER_ID"
    assert ITEM_ID not in str(captured.value)
    assert CLIENT_USER_ID not in str(captured.value)


def test_connected_item_rejects_cross_residence_ownership() -> None:
    other_client_user_id = "residence:30000000-0000-4000-8000-000000000003"

    with pytest.raises(PluggyGatewayError) as captured:
        parse_connected_item(
            item_payload(clientUserId=other_client_user_id),
            expected_item_id=ITEM_ID,
            expected_client_user_id=CLIENT_USER_ID,
            clock=lambda: NOW,
        )

    assert captured.value.category is PluggyGatewayErrorCategory.AUTHORIZATION
    assert captured.value.provider_reason_code == "ITEM_OWNERSHIP_MISMATCH"
    assert CLIENT_USER_ID not in str(captured.value)
    assert other_client_user_id not in str(captured.value)


@pytest.mark.parametrize(
    "client_user_id",
    [
        "residence:bad\nmarker",
        "x" * 513,
    ],
)
def test_connected_item_rejects_invalid_ownership_marker(
    client_user_id: str,
) -> None:
    with pytest.raises(PluggyGatewayError) as captured:
        parse_connected_item(
            item_payload(clientUserId=client_user_id),
            expected_item_id=ITEM_ID,
            expected_client_user_id=CLIENT_USER_ID,
            clock=lambda: NOW,
        )

    assert captured.value.category is PluggyGatewayErrorCategory.INTERNAL
    assert captured.value.provider_reason_code == "INVALID_ITEM_CLIENT_USER_ID"
    assert client_user_id not in str(captured.value)
