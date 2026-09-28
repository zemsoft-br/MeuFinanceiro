from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from meufinanceiro_persistence import (
    BankingLedgerReviewCandidate,
    BankingLedgerReviewDecision,
    BankingLedgerReviewDraft,
    BankingLedgerReviewRecord,
    StoredTransactionObservationStatus,
)

NOW = datetime(2026, 8, 16, 4, 0, tzinfo=UTC)


def test_candidate_is_provider_neutral_and_redacted() -> None:
    candidate = BankingLedgerReviewCandidate(
        reconciled_transaction_id=uuid4(),
        external_account_record_id=uuid4(),
        status=StoredTransactionObservationStatus.CONFIRMED,
        effective_date=date(2026, 8, 15),
        amount=Decimal("125.50"),
        currency="BRL",
        description="Synthetic reviewed transaction",
        source_observation_id=uuid4(),
        source_observation_updated_at=NOW,
    )

    rendered = repr(candidate)
    assert "125.50" not in rendered
    assert "Synthetic reviewed transaction" not in rendered
    assert str(candidate.reconciled_transaction_id) not in rendered
    assert "CONFIRMED" in rendered
    assert "BRL" in rendered


def test_review_draft_enforces_decision_target_shape() -> None:
    source_id = uuid4()
    account_id = uuid4()
    movement_id = uuid4()

    income = BankingLedgerReviewDraft(
        source_observation_id=source_id,
        source_observation_updated_at=NOW,
        decision=BankingLedgerReviewDecision.IMPORT_AS_INCOME,
        financial_account_id=account_id,
    )
    assert income.financial_account_id == account_id
    assert income.movement_id is None

    linked = BankingLedgerReviewDraft(
        source_observation_id=source_id,
        source_observation_updated_at=NOW,
        decision=BankingLedgerReviewDecision.LINK_EXISTING_MOVEMENT,
        movement_id=movement_id,
    )
    assert linked.movement_id == movement_id
    assert linked.financial_account_id is None

    ignored = BankingLedgerReviewDraft(
        source_observation_id=source_id,
        source_observation_updated_at=NOW,
        decision=BankingLedgerReviewDecision.IGNORE,
    )
    assert ignored.movement_id is None

    with pytest.raises(ValueError):
        BankingLedgerReviewDraft(
            source_observation_id=source_id,
            source_observation_updated_at=NOW,
            decision=BankingLedgerReviewDecision.IMPORT_AS_EXPENSE,
        )
    with pytest.raises(ValueError):
        BankingLedgerReviewDraft(
            source_observation_id=source_id,
            source_observation_updated_at=NOW,
            decision=BankingLedgerReviewDecision.LINK_EXISTING_MOVEMENT,
            financial_account_id=account_id,
            movement_id=movement_id,
        )
    with pytest.raises(ValueError):
        BankingLedgerReviewDraft(
            source_observation_id=source_id,
            source_observation_updated_at=NOW,
            decision=BankingLedgerReviewDecision.IGNORE,
            movement_id=movement_id,
        )


def test_record_repr_does_not_expose_local_identities() -> None:
    record = BankingLedgerReviewRecord(
        id=uuid4(),
        reconciled_transaction_id=uuid4(),
        source_observation_id=uuid4(),
        source_observation_updated_at=NOW,
        decision=BankingLedgerReviewDecision.LINK_EXISTING_MOVEMENT,
        financial_account_id=uuid4(),
        movement_id=uuid4(),
        decided_by_operator_id=uuid4(),
        decided_at=NOW,
    )

    rendered = repr(record)
    assert record.decision.value in rendered
    assert "has_movement=True" in rendered
    assert str(record.id) not in rendered
    assert str(record.movement_id) not in rendered
    assert str(record.source_observation_id) not in rendered
