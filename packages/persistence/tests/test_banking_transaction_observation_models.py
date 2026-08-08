from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from meufinanceiro_persistence.banking import (
    StoredTransactionObservationStatus,
    TransactionObservationSnapshot,
)

OBSERVED_AT = datetime(2026, 8, 8, 4, 15, tzinfo=UTC)


def _snapshot(
    *,
    status: StoredTransactionObservationStatus = (
        StoredTransactionObservationStatus.PENDING
    ),
    external_resource_id: str | None = "provider-transaction-001",
    amount: Decimal = Decimal("123.45000000"),
    description: str | None = "Compra sintética",
) -> TransactionObservationSnapshot:
    return TransactionObservationSnapshot(
        external_account_id="synthetic-account-001",
        external_resource_id=external_resource_id,
        status=status,
        provider_updated_at=OBSERVED_AT,
        effective_date=date(2026, 8, 8),
        amount=amount,
        currency="BRL",
        description=description,
        category="synthetic-category",
        observed_at=OBSERVED_AT,
    )


def test_provider_id_fingerprint_is_stable_across_status_and_metadata_updates() -> None:
    pending = _snapshot()
    confirmed = TransactionObservationSnapshot(
        external_account_id=pending.external_account_id,
        external_resource_id=pending.external_resource_id,
        status=StoredTransactionObservationStatus.CONFIRMED,
        provider_updated_at=OBSERVED_AT,
        effective_date=date(2026, 8, 9),
        amount=Decimal("999.99"),
        currency="BRL",
        description="Descrição atualizada",
        category="updated",
        observed_at=OBSERVED_AT,
    )

    assert pending.stable_fingerprint == confirmed.stable_fingerprint
    assert len(pending.stable_fingerprint) == 64
    assert pending.stable_fingerprint.isascii()
    assert pending.normalized_payload_version == 1


def test_content_fingerprint_is_deterministic_without_provider_id() -> None:
    first = _snapshot(external_resource_id=None, amount=Decimal("10.5000"))
    same = _snapshot(external_resource_id=None, amount=Decimal("10.50"))
    changed = _snapshot(
        external_resource_id=None,
        amount=Decimal("10.51"),
    )

    assert first.stable_fingerprint == same.stable_fingerprint
    assert first.stable_fingerprint != changed.stable_fingerprint


def test_status_does_not_change_content_fingerprint_without_provider_id() -> None:
    pending = _snapshot(
        external_resource_id=None,
        status=StoredTransactionObservationStatus.PENDING,
    )
    confirmed = _snapshot(
        external_resource_id=None,
        status=StoredTransactionObservationStatus.CONFIRMED,
    )

    assert pending.stable_fingerprint == confirmed.stable_fingerprint


def test_inferred_observation_cannot_claim_provider_resource_id() -> None:
    with pytest.raises(ValueError, match="cannot claim"):
        _snapshot(status=StoredTransactionObservationStatus.INFERRED)

    inferred = _snapshot(
        status=StoredTransactionObservationStatus.INFERRED,
        external_resource_id=None,
    )
    assert inferred.external_resource_id is None


def test_deleted_status_derives_deleted_at_from_observation_time() -> None:
    deleted = _snapshot(status=StoredTransactionObservationStatus.DELETED)
    active = _snapshot(status=StoredTransactionObservationStatus.CONFIRMED)

    assert deleted.deleted_at == OBSERVED_AT
    assert active.deleted_at is None


def test_amount_requires_decimal_and_database_compatible_precision() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        TransactionObservationSnapshot(
            external_account_id="synthetic-account",
            external_resource_id="synthetic-resource",
            status=StoredTransactionObservationStatus.CONFIRMED,
            effective_date=date(2026, 8, 8),
            amount=10.5,  # type: ignore[arg-type]
            currency="BRL",
            observed_at=OBSERVED_AT,
        )

    for invalid in (
        Decimal("1.000000001"),
        Decimal("10000000000000000"),
        Decimal("1E+20"),
        Decimal("NaN"),
        Decimal("Infinity"),
    ):
        with pytest.raises(ValueError):
            _snapshot(amount=invalid)


def test_snapshot_rejects_unaware_time_and_invalid_currency() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        TransactionObservationSnapshot(
            external_account_id="synthetic-account",
            status=StoredTransactionObservationStatus.CONFIRMED,
            effective_date=date(2026, 8, 8),
            amount=Decimal("1.00"),
            currency="BRL",
            observed_at=datetime(2026, 8, 8, 4, 15),
        )

    with pytest.raises(ValueError, match="currency"):
        TransactionObservationSnapshot(
            external_account_id="synthetic-account",
            status=StoredTransactionObservationStatus.CONFIRMED,
            effective_date=date(2026, 8, 8),
            amount=Decimal("1.00"),
            currency="brl",
            observed_at=OBSERVED_AT,
        )


def test_repr_redacts_financial_and_external_material() -> None:
    snapshot = _snapshot()
    rendered = repr(snapshot)

    for forbidden in (
        "provider-transaction-001",
        "synthetic-account-001",
        "123.45",
        "Compra sintética",
        snapshot.stable_fingerprint,
    ):
        assert forbidden not in rendered
