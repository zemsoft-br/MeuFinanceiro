from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from meufinanceiro_persistence import (
    ReconciledTransactionIdentityKind,
    ReconciledTransactionRecord,
    StoredTransactionObservationStatus,
    TransactionReconciliationResult,
)

NOW = datetime(2026, 8, 9, 23, 0, tzinfo=UTC)


def test_reconciled_transaction_repr_redacts_identity_and_scope() -> None:
    record = ReconciledTransactionRecord(
        id=uuid4(),
        residence_id=uuid4(),
        connection_id=uuid4(),
        external_account_record_id=uuid4(),
        identity_kind=ReconciledTransactionIdentityKind.PROVIDER_ID,
        identity_digest="a" * 64,
        status=StoredTransactionObservationStatus.CONFIRMED,
        source_observation_id=uuid4(),
        source_observed_at=NOW,
        first_reconciled_at=NOW,
        updated_at=NOW,
    )

    rendered = repr(record)
    assert record.identity_digest not in rendered
    assert str(record.id) not in rendered
    assert str(record.residence_id) not in rendered
    assert str(record.connection_id) not in rendered
    assert str(record.external_account_record_id) not in rendered
    assert str(record.source_observation_id) not in rendered
    assert "PROVIDER_ID" in rendered
    assert "CONFIRMED" in rendered


def test_reconciliation_result_contains_only_bounded_counters() -> None:
    result = TransactionReconciliationResult(
        observations_seen=3,
        identities_created=1,
        identities_updated=1,
        identities_unchanged=1,
        has_more=True,
    )

    assert repr(result) == (
        "TransactionReconciliationResult("
        "observations_seen=3, identities_created=1, identities_updated=1, "
        "identities_unchanged=1, has_more=True)"
    )


def test_reconciliation_result_rejects_inconsistent_counters() -> None:
    with pytest.raises(ValueError):
        TransactionReconciliationResult(
            observations_seen=2,
            identities_created=1,
            identities_updated=0,
            identities_unchanged=0,
            has_more=False,
        )


def test_reconciled_transaction_rejects_non_sha256_digest() -> None:
    with pytest.raises(ValueError):
        ReconciledTransactionRecord(
            id=uuid4(),
            residence_id=uuid4(),
            connection_id=uuid4(),
            external_account_record_id=uuid4(),
            identity_kind=ReconciledTransactionIdentityKind.FINGERPRINT,
            identity_digest="not-a-digest",
            status=StoredTransactionObservationStatus.INFERRED,
            source_observation_id=uuid4(),
            source_observed_at=NOW,
            first_reconciled_at=NOW,
            updated_at=NOW,
        )
