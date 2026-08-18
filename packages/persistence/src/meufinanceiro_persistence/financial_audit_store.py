"""Connection-scoped append-only financial audit persistence."""

from __future__ import annotations

from uuid import UUID

from meufinanceiro_finance import (
    FinancialAuditEventDraft,
    FinancialAuditEventRecord,
    FinancialAuditEventType,
    FinancialAuditSubjectType,
    validate_financial_resource_id,
)
from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.financial_audit_schema import financial_audit_events
from meufinanceiro_persistence.household_schema import household_memberships


class FinancialAuditPersistenceError(RuntimeError):
    """Sanitized persistence failure for the financial audit trail."""


class FinancialAuditAccessError(FinancialAuditPersistenceError):
    """Actor has no active membership in the requested residence."""


class FinancialAuditNotFoundError(FinancialAuditPersistenceError):
    """Audit event is missing or outside the actor-only audience."""


def _append_financial_audit_event(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    actor_operator_id: UUID,
    draft: FinancialAuditEventDraft,
) -> UUID:
    """Append one audit event inside the caller's existing transaction."""
    if not isinstance(connection, Connection):
        raise TypeError("connection must be SQLAlchemy Connection")
    _require_uuid(installation_id, "installation_id")
    _require_uuid(residence_id, "residence_id")
    _require_uuid(actor_operator_id, "actor_operator_id")
    if not isinstance(draft, FinancialAuditEventDraft):
        raise TypeError("draft must be FinancialAuditEventDraft")

    event_id = connection.scalar(
        select(
            func.finance.append_financial_audit_event(
                installation_id,
                residence_id,
                actor_operator_id,
                draft.event_type.value,
                draft.subject_id,
                draft.related_subject_id,
            )
        )
    )
    if not isinstance(event_id, UUID):
        raise FinancialAuditPersistenceError("financial audit event could not be persisted")
    return event_id


class FinancialAuditStore:
    """Read actor-only financial audit events through PostgreSQL RLS."""

    def __init__(self, engine: Engine) -> None:
        if not isinstance(engine, Engine):
            raise TypeError("engine must be SQLAlchemy Engine")
        self._engine = engine

    def get_event(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        event_id: UUID,
    ) -> FinancialAuditEventRecord:
        _validate_scope(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
        )
        validate_financial_resource_id(event_id)
        try:
            with self._engine.begin() as connection:
                _prepare_connection(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )
                row = (
                    connection.execute(
                        select(financial_audit_events).where(
                            financial_audit_events.c.id == event_id,
                            financial_audit_events.c.installation_id == installation_id,
                            financial_audit_events.c.residence_id == residence_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except FinancialAuditAccessError:
            raise
        except DBAPIError:
            raise FinancialAuditPersistenceError(
                "financial audit event could not be read"
            ) from None
        if row is None:
            raise FinancialAuditNotFoundError("financial audit event was not found")
        return _record(row)

    def list_events(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
    ) -> tuple[FinancialAuditEventRecord, ...]:
        _validate_scope(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
        )
        try:
            with self._engine.begin() as connection:
                _prepare_connection(
                    connection,
                    installation_id=installation_id,
                    residence_id=residence_id,
                    operator_id=operator_id,
                )
                rows = (
                    connection.execute(
                        select(financial_audit_events)
                        .where(
                            financial_audit_events.c.installation_id == installation_id,
                            financial_audit_events.c.residence_id == residence_id,
                        )
                        .order_by(
                            financial_audit_events.c.occurred_at,
                            financial_audit_events.c.id,
                        )
                    )
                    .mappings()
                    .all()
                )
        except FinancialAuditAccessError:
            raise
        except DBAPIError:
            raise FinancialAuditPersistenceError(
                "financial audit events could not be read"
            ) from None
        return tuple(_record(row) for row in rows)


def _prepare_connection(
    connection: Connection,
    *,
    installation_id: UUID,
    residence_id: UUID,
    operator_id: UUID,
) -> None:
    connection.execute(
        select(
            func.set_config(
                "app.current_installation_id",
                str(installation_id),
                True,
            ),
            func.set_config(
                "app.current_residence_id",
                str(residence_id),
                True,
            ),
            func.set_config(
                "app.current_operator_id",
                str(operator_id),
                True,
            ),
        )
    )
    membership_id = connection.scalar(
        select(household_memberships.c.id).where(
            household_memberships.c.installation_id == installation_id,
            household_memberships.c.residence_id == residence_id,
            household_memberships.c.operator_id == operator_id,
            household_memberships.c.status == "active",
        )
    )
    if membership_id is None:
        raise FinancialAuditAccessError("financial audit access denied")


def _record(row: RowMapping) -> FinancialAuditEventRecord:
    try:
        return FinancialAuditEventRecord(
            id=row["id"],
            residence_id=row["residence_id"],
            actor_operator_id=row["actor_operator_id"],
            event_type=FinancialAuditEventType(row["event_type"]),
            subject_type=FinancialAuditSubjectType(row["subject_type"]),
            subject_id=row["subject_id"],
            related_subject_type=(
                FinancialAuditSubjectType(row["related_subject_type"])
                if row["related_subject_type"] is not None
                else None
            ),
            related_subject_id=row["related_subject_id"],
            event_schema_version=int(row["event_schema_version"]),
            occurred_at=row["occurred_at"],
        )
    except (KeyError, TypeError, ValueError):
        raise FinancialAuditPersistenceError("financial audit event state is invalid") from None


def _validate_scope(
    *, installation_id: UUID, residence_id: UUID, operator_id: UUID
) -> None:
    _require_uuid(installation_id, "installation_id")
    _require_uuid(residence_id, "residence_id")
    _require_uuid(operator_id, "operator_id")


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


__all__ = [
    "FinancialAuditAccessError",
    "FinancialAuditNotFoundError",
    "FinancialAuditPersistenceError",
    "FinancialAuditStore",
]
