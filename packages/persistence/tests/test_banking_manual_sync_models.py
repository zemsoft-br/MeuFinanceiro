from __future__ import annotations

from datetime import UTC, datetime

import pytest

from meufinanceiro_persistence.banking import (
    ExternalAccountSnapshot,
    StoredExternalAccountStatus,
    StoredExternalAccountType,
    StoredSyncErrorCategory,
    StoredSyncStatus,
)
from meufinanceiro_persistence.banking_models import (
    clean_cursor,
    clean_idempotency_key,
    clean_source_window,
    validate_sync_completion,
)

NOW = datetime(2026, 8, 8, 3, 30, tzinfo=UTC)


def test_external_account_snapshot_rejects_unminimized_or_unsafe_values() -> None:
    with pytest.raises(ValueError, match="full numeric account number"):
        ExternalAccountSnapshot(
            external_account_id="synthetic-account",
            account_type=StoredExternalAccountType.BANK,
            subtype="CHECKING_ACCOUNT",
            currency="BRL",
            status=StoredExternalAccountStatus.ACTIVE,
            observed_at=NOW,
            number_mask="123456789",
        )

    with pytest.raises(ValueError, match="timezone-aware"):
        ExternalAccountSnapshot(
            external_account_id="synthetic-account",
            account_type=StoredExternalAccountType.BANK,
            subtype="CHECKING_ACCOUNT",
            currency="BRL",
            status=StoredExternalAccountStatus.ACTIVE,
            observed_at=datetime(2026, 8, 8, 3, 30),
            number_mask="1234",
        )

    with pytest.raises(ValueError, match="currency"):
        ExternalAccountSnapshot(
            external_account_id="synthetic-account",
            account_type=StoredExternalAccountType.BANK,
            subtype="CHECKING_ACCOUNT",
            currency="brl",
            status=StoredExternalAccountStatus.ACTIVE,
            observed_at=NOW,
            number_mask="1234",
        )


def test_opaque_cursor_material_is_bounded_and_not_normalized() -> None:
    assert clean_cursor("opaque-cursor") == "opaque-cursor"
    assert clean_source_window("2026-07-01..2026-08-01") == "2026-07-01..2026-08-01"

    for invalid in ("", " cursor", "cursor ", "cursor\nvalue"):
        with pytest.raises((TypeError, ValueError)):
            clean_cursor(invalid)

    with pytest.raises(ValueError):
        clean_source_window("x" * 257)


def test_idempotency_key_and_completion_contract_fail_closed() -> None:
    assert clean_idempotency_key("manual-sync:2026-08-08.001") == (
        "manual-sync:2026-08-08.001"
    )
    for invalid in ("", "has space", "x" * 201):
        with pytest.raises(ValueError):
            clean_idempotency_key(invalid)

    with pytest.raises(ValueError, match="terminal"):
        validate_sync_completion(
            status=StoredSyncStatus.RUNNING,
            error_category=None,
            provider_reason_code=None,
            http_status=None,
            retry_window_bucket=None,
            records_seen=0,
            records_applied=0,
        )

    with pytest.raises(ValueError, match="record counts"):
        validate_sync_completion(
            status=StoredSyncStatus.FAILED,
            error_category=StoredSyncErrorCategory.INTERNAL,
            provider_reason_code=None,
            http_status=500,
            retry_window_bucket=None,
            records_seen=1,
            records_applied=2,
        )
