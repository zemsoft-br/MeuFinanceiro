"""Persisted immutable records for financial audit events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from meufinanceiro_finance.audit_events import (
    FINANCIAL_AUDIT_EVENT_SCHEMA_VERSION,
    FinancialAuditEventDraft,
    FinancialAuditEventType,
    FinancialAuditSubjectType,
)
from meufinanceiro_finance.ids import validate_financial_resource_id


@dataclass(frozen=True, slots=True, repr=False)
class FinancialAuditEventRecord:
    """One persisted successful financial mutation audit event."""

    id: UUID
    residence_id: UUID
    actor_operator_id: UUID
    event_type: FinancialAuditEventType
    subject_type: FinancialAuditSubjectType
    subject_id: UUID
    related_subject_type: FinancialAuditSubjectType | None
    related_subject_id: UUID | None
    event_schema_version: int
    occurred_at: datetime

    def __post_init__(self) -> None:
        validate_financial_resource_id(self.id)
        _require_uuid(self.residence_id, "residence_id")
        _require_uuid(self.actor_operator_id, "actor_operator_id")
        if not isinstance(self.event_type, FinancialAuditEventType):
            raise TypeError("event_type must be FinancialAuditEventType")
        if not isinstance(self.subject_type, FinancialAuditSubjectType):
            raise TypeError("subject_type must be FinancialAuditSubjectType")
        if self.related_subject_type is not None and not isinstance(
            self.related_subject_type,
            FinancialAuditSubjectType,
        ):
            raise TypeError(
                "related_subject_type must be FinancialAuditSubjectType or None"
            )
        validate_financial_resource_id(self.subject_id)
        if self.related_subject_id is not None:
            validate_financial_resource_id(self.related_subject_id)
        if isinstance(self.event_schema_version, bool) or not isinstance(
            self.event_schema_version, int
        ):
            raise TypeError("event_schema_version must be an integer")
        if self.event_schema_version != FINANCIAL_AUDIT_EVENT_SCHEMA_VERSION:
            raise ValueError("unsupported financial audit event schema version")
        _require_aware(self.occurred_at, "occurred_at")

        draft = FinancialAuditEventDraft(
            event_type=self.event_type,
            subject_id=self.subject_id,
            related_subject_id=self.related_subject_id,
        )
        if self.subject_type is not draft.subject_type:
            raise ValueError("audit subject type does not match event type")
        if self.related_subject_type is not draft.related_subject_type:
            raise ValueError("audit related subject type does not match event type")

    def __repr__(self) -> str:
        return (
            "FinancialAuditEventRecord("
            f"event_type={self.event_type.value!r}, "
            f"subject_type={self.subject_type.value!r}, "
            f"event_schema_version={self.event_schema_version}, "
            f"has_related_subject={self.related_subject_id is not None}, "
            "<event-actor-and-subject-identities-redacted>)"
        )


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


__all__ = ["FinancialAuditEventRecord"]
