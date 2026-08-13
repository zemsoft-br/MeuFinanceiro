"""Provider-neutral contracts for append-only financial audit events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from meufinanceiro_finance.ids import validate_financial_resource_id

FINANCIAL_AUDIT_EVENT_SCHEMA_VERSION = 1


class FinancialAuditSubjectType(StrEnum):
    """Closed set of canonical financial resource types that may be audited."""

    ACCOUNT = "ACCOUNT"
    CATEGORY = "CATEGORY"
    OPENING_BALANCE = "OPENING_BALANCE"
    MOVEMENT = "MOVEMENT"
    TRANSFER = "TRANSFER"
    ALLOCATION_SET = "ALLOCATION_SET"


class FinancialAuditEventType(StrEnum):
    """Closed set of successful financial mutation events."""

    ACCOUNT_CREATED = "ACCOUNT_CREATED"
    CATEGORY_CREATED = "CATEGORY_CREATED"
    OPENING_BALANCE_CREATED = "OPENING_BALANCE_CREATED"
    MOVEMENT_CREATED = "MOVEMENT_CREATED"
    MOVEMENT_REVERSED = "MOVEMENT_REVERSED"
    TRANSFER_CREATED = "TRANSFER_CREATED"
    TRANSFER_REVERSED = "TRANSFER_REVERSED"
    ALLOCATION_SET_CREATED = "ALLOCATION_SET_CREATED"
    ALLOCATION_SET_REVISED = "ALLOCATION_SET_REVISED"


_SUBJECT_BY_EVENT = {
    FinancialAuditEventType.ACCOUNT_CREATED: FinancialAuditSubjectType.ACCOUNT,
    FinancialAuditEventType.CATEGORY_CREATED: FinancialAuditSubjectType.CATEGORY,
    FinancialAuditEventType.OPENING_BALANCE_CREATED: FinancialAuditSubjectType.OPENING_BALANCE,
    FinancialAuditEventType.MOVEMENT_CREATED: FinancialAuditSubjectType.MOVEMENT,
    FinancialAuditEventType.MOVEMENT_REVERSED: FinancialAuditSubjectType.MOVEMENT,
    FinancialAuditEventType.TRANSFER_CREATED: FinancialAuditSubjectType.TRANSFER,
    FinancialAuditEventType.TRANSFER_REVERSED: FinancialAuditSubjectType.TRANSFER,
    FinancialAuditEventType.ALLOCATION_SET_CREATED: FinancialAuditSubjectType.ALLOCATION_SET,
    FinancialAuditEventType.ALLOCATION_SET_REVISED: FinancialAuditSubjectType.ALLOCATION_SET,
}

_RELATED_SUBJECT_BY_EVENT: dict[
    FinancialAuditEventType,
    FinancialAuditSubjectType | None,
] = {
    FinancialAuditEventType.ACCOUNT_CREATED: None,
    FinancialAuditEventType.CATEGORY_CREATED: None,
    FinancialAuditEventType.OPENING_BALANCE_CREATED: None,
    FinancialAuditEventType.MOVEMENT_CREATED: None,
    FinancialAuditEventType.MOVEMENT_REVERSED: FinancialAuditSubjectType.MOVEMENT,
    FinancialAuditEventType.TRANSFER_CREATED: None,
    FinancialAuditEventType.TRANSFER_REVERSED: FinancialAuditSubjectType.TRANSFER,
    FinancialAuditEventType.ALLOCATION_SET_CREATED: None,
    FinancialAuditEventType.ALLOCATION_SET_REVISED: FinancialAuditSubjectType.ALLOCATION_SET,
}


@dataclass(frozen=True, slots=True, repr=False)
class FinancialAuditEventDraft:
    """Minimal successful-mutation audit intent without financial payload copies."""

    event_type: FinancialAuditEventType
    subject_id: UUID
    related_subject_id: UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.event_type, FinancialAuditEventType):
            raise TypeError("event_type must be FinancialAuditEventType")
        validate_financial_resource_id(self.subject_id)

        expected_related = _RELATED_SUBJECT_BY_EVENT[self.event_type]
        if expected_related is None:
            if self.related_subject_id is not None:
                raise ValueError("audit event must not have related subject")
            return

        if self.related_subject_id is None:
            raise ValueError("audit event requires related subject")
        validate_financial_resource_id(self.related_subject_id)
        if self.related_subject_id == self.subject_id:
            raise ValueError("audit related subject must differ from subject")

    @property
    def subject_type(self) -> FinancialAuditSubjectType:
        return _SUBJECT_BY_EVENT[self.event_type]

    @property
    def related_subject_type(self) -> FinancialAuditSubjectType | None:
        return _RELATED_SUBJECT_BY_EVENT[self.event_type]

    @property
    def event_schema_version(self) -> int:
        return FINANCIAL_AUDIT_EVENT_SCHEMA_VERSION

    def __repr__(self) -> str:
        return (
            "FinancialAuditEventDraft("
            f"event_type={self.event_type.value!r}, "
            f"subject_type={self.subject_type.value!r}, "
            f"has_related_subject={self.related_subject_id is not None}, "
            "<subject-identities-redacted>)"
        )


def financial_audit_subject_type_for_event(
    event_type: FinancialAuditEventType,
) -> FinancialAuditSubjectType:
    """Return the only valid subject type for one event type."""
    if not isinstance(event_type, FinancialAuditEventType):
        raise TypeError("event_type must be FinancialAuditEventType")
    return _SUBJECT_BY_EVENT[event_type]


def financial_audit_related_subject_type_for_event(
    event_type: FinancialAuditEventType,
) -> FinancialAuditSubjectType | None:
    """Return the required related subject type, if any, for one event type."""
    if not isinstance(event_type, FinancialAuditEventType):
        raise TypeError("event_type must be FinancialAuditEventType")
    return _RELATED_SUBJECT_BY_EVENT[event_type]


__all__ = [
    "FINANCIAL_AUDIT_EVENT_SCHEMA_VERSION",
    "FinancialAuditEventDraft",
    "FinancialAuditEventType",
    "FinancialAuditSubjectType",
    "financial_audit_related_subject_type_for_event",
    "financial_audit_subject_type_for_event",
]
