from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from meufinanceiro_finance.audit_event_records import FinancialAuditEventRecord
from meufinanceiro_finance.audit_events import (
    FINANCIAL_AUDIT_EVENT_SCHEMA_VERSION,
    FinancialAuditEventDraft,
    FinancialAuditEventType,
    FinancialAuditSubjectType,
    financial_audit_related_subject_type_for_event,
    financial_audit_subject_type_for_event,
)


@pytest.mark.parametrize(
    ("event_type", "subject_type", "related_type"),
    (
        (
            FinancialAuditEventType.ACCOUNT_CREATED,
            FinancialAuditSubjectType.ACCOUNT,
            None,
        ),
        (
            FinancialAuditEventType.CATEGORY_CREATED,
            FinancialAuditSubjectType.CATEGORY,
            None,
        ),
        (
            FinancialAuditEventType.OPENING_BALANCE_CREATED,
            FinancialAuditSubjectType.OPENING_BALANCE,
            None,
        ),
        (
            FinancialAuditEventType.MOVEMENT_CREATED,
            FinancialAuditSubjectType.MOVEMENT,
            None,
        ),
        (
            FinancialAuditEventType.MOVEMENT_REVERSED,
            FinancialAuditSubjectType.MOVEMENT,
            FinancialAuditSubjectType.MOVEMENT,
        ),
        (
            FinancialAuditEventType.TRANSFER_CREATED,
            FinancialAuditSubjectType.TRANSFER,
            None,
        ),
        (
            FinancialAuditEventType.TRANSFER_REVERSED,
            FinancialAuditSubjectType.TRANSFER,
            FinancialAuditSubjectType.TRANSFER,
        ),
        (
            FinancialAuditEventType.ALLOCATION_SET_CREATED,
            FinancialAuditSubjectType.ALLOCATION_SET,
            None,
        ),
        (
            FinancialAuditEventType.ALLOCATION_SET_REVISED,
            FinancialAuditSubjectType.ALLOCATION_SET,
            FinancialAuditSubjectType.ALLOCATION_SET,
        ),
    ),
)
def test_event_type_closes_subject_and_related_subject_matrix(
    event_type: FinancialAuditEventType,
    subject_type: FinancialAuditSubjectType,
    related_type: FinancialAuditSubjectType | None,
) -> None:
    assert financial_audit_subject_type_for_event(event_type) is subject_type
    assert financial_audit_related_subject_type_for_event(event_type) is related_type


def test_simple_creation_event_must_not_have_related_subject() -> None:
    subject_id = uuid4()
    draft = FinancialAuditEventDraft(
        event_type=FinancialAuditEventType.ACCOUNT_CREATED,
        subject_id=subject_id,
    )
    assert draft.subject_type is FinancialAuditSubjectType.ACCOUNT
    assert draft.related_subject_type is None
    assert draft.event_schema_version == FINANCIAL_AUDIT_EVENT_SCHEMA_VERSION

    with pytest.raises(ValueError, match="must not have related"):
        FinancialAuditEventDraft(
            event_type=FinancialAuditEventType.ACCOUNT_CREATED,
            subject_id=subject_id,
            related_subject_id=uuid4(),
        )


def test_reversal_event_requires_distinct_related_subject() -> None:
    reversal_id = uuid4()
    original_id = uuid4()
    draft = FinancialAuditEventDraft(
        event_type=FinancialAuditEventType.MOVEMENT_REVERSED,
        subject_id=reversal_id,
        related_subject_id=original_id,
    )
    assert draft.subject_type is FinancialAuditSubjectType.MOVEMENT
    assert draft.related_subject_type is FinancialAuditSubjectType.MOVEMENT

    with pytest.raises(ValueError, match="requires related"):
        FinancialAuditEventDraft(
            event_type=FinancialAuditEventType.MOVEMENT_REVERSED,
            subject_id=reversal_id,
        )

    with pytest.raises(ValueError, match="must differ"):
        FinancialAuditEventDraft(
            event_type=FinancialAuditEventType.MOVEMENT_REVERSED,
            subject_id=reversal_id,
            related_subject_id=reversal_id,
        )


def test_allocation_revision_requires_allocation_set_predecessor() -> None:
    draft = FinancialAuditEventDraft(
        event_type=FinancialAuditEventType.ALLOCATION_SET_REVISED,
        subject_id=uuid4(),
        related_subject_id=uuid4(),
    )
    assert draft.subject_type is FinancialAuditSubjectType.ALLOCATION_SET
    assert draft.related_subject_type is FinancialAuditSubjectType.ALLOCATION_SET


def test_record_rejects_subject_type_mismatch() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="subject type does not match"):
        FinancialAuditEventRecord(
            id=uuid4(),
            residence_id=uuid4(),
            actor_operator_id=uuid4(),
            event_type=FinancialAuditEventType.MOVEMENT_CREATED,
            subject_type=FinancialAuditSubjectType.ACCOUNT,
            subject_id=uuid4(),
            related_subject_type=None,
            related_subject_id=None,
            event_schema_version=FINANCIAL_AUDIT_EVENT_SCHEMA_VERSION,
            occurred_at=now,
        )


def test_record_rejects_unsupported_schema_version() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        FinancialAuditEventRecord(
            id=uuid4(),
            residence_id=uuid4(),
            actor_operator_id=uuid4(),
            event_type=FinancialAuditEventType.CATEGORY_CREATED,
            subject_type=FinancialAuditSubjectType.CATEGORY,
            subject_id=uuid4(),
            related_subject_type=None,
            related_subject_id=None,
            event_schema_version=2,
            occurred_at=datetime.now(UTC),
        )


def test_repr_redacts_actor_and_resource_ids() -> None:
    event_id = uuid4()
    residence_id = uuid4()
    actor_id = uuid4()
    subject_id = uuid4()
    record = FinancialAuditEventRecord(
        id=event_id,
        residence_id=residence_id,
        actor_operator_id=actor_id,
        event_type=FinancialAuditEventType.ACCOUNT_CREATED,
        subject_type=FinancialAuditSubjectType.ACCOUNT,
        subject_id=subject_id,
        related_subject_type=None,
        related_subject_id=None,
        event_schema_version=FINANCIAL_AUDIT_EVENT_SCHEMA_VERSION,
        occurred_at=datetime.now(UTC),
    )
    rendered = repr(record)
    for sensitive in (event_id, residence_id, actor_id, subject_id):
        assert str(sensitive) not in rendered
