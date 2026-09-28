"""Persistent PostgreSQL task queue with leases and idempotent enqueue."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Mapping
from uuid import UUID, uuid4

from meufinanceiro_security.redaction import redact_text
from sqlalchemy import Engine, and_, delete, func, or_, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from meufinanceiro_persistence.schema import task_queue

MAX_ERROR_LENGTH = 2_000


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class LostLeaseError(RuntimeError):
    """Raised when a worker tries to mutate a task it no longer owns."""


@dataclass(frozen=True, slots=True)
class TaskRecord:
    id: UUID
    task_type: str
    payload: dict[str, Any]
    status: TaskStatus
    idempotency_key: str
    correlation_id: UUID
    attempts: int
    max_attempts: int
    available_at: datetime
    locked_at: datetime | None
    lease_expires_at: datetime | None
    locked_by: str | None
    lease_token: UUID | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    @classmethod
    def from_mapping(cls, row: RowMapping) -> TaskRecord:
        payload = row["payload"]
        return cls(
            id=row["id"],
            task_type=row["task_type"],
            payload=dict(payload),
            status=TaskStatus(row["status"]),
            idempotency_key=row["idempotency_key"],
            correlation_id=row["correlation_id"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            available_at=row["available_at"],
            locked_at=row["locked_at"],
            lease_expires_at=row["lease_expires_at"],
            locked_by=row["locked_by"],
            lease_token=row["lease_token"],
            last_error=row["last_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )


class TaskQueue:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def enqueue(
        self,
        *,
        task_type: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
        correlation_id: UUID | None = None,
        available_at: datetime | None = None,
        max_attempts: int = 3,
    ) -> TaskRecord:
        if not task_type.strip() or len(task_type) > 100:
            raise ValueError("task_type must contain between 1 and 100 characters")
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise ValueError(
                "idempotency_key must contain between 1 and 200 characters"
            )
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")

        database_now = func.now()
        insert_statement = postgresql_insert(task_queue).values(
            id=uuid4(),
            task_type=task_type,
            payload=dict(payload),
            status=TaskStatus.PENDING.value,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id or uuid4(),
            attempts=0,
            max_attempts=max_attempts,
            available_at=available_at if available_at is not None else database_now,
            locked_at=None,
            lease_expires_at=None,
            locked_by=None,
            lease_token=None,
            last_error=None,
            created_at=database_now,
            updated_at=database_now,
            completed_at=None,
        )
        statement = insert_statement.on_conflict_do_update(
            index_elements=[task_queue.c.idempotency_key],
            set_={"idempotency_key": insert_statement.excluded.idempotency_key},
        ).returning(*task_queue.c)

        with self._engine.begin() as connection:
            row = connection.execute(statement).mappings().one()
        return TaskRecord.from_mapping(row)

    def claim(self, *, worker_id: str, lease_seconds: int) -> TaskRecord | None:
        if not worker_id.strip() or len(worker_id) > 200:
            raise ValueError("worker_id must contain between 1 and 200 characters")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")

        database_now = func.now()
        lease_token = uuid4()
        candidate = (
            select(task_queue.c.id)
            .where(
                task_queue.c.attempts < task_queue.c.max_attempts,
                or_(
                    and_(
                        task_queue.c.status == TaskStatus.PENDING.value,
                        task_queue.c.available_at <= database_now,
                    ),
                    and_(
                        task_queue.c.status == TaskStatus.RUNNING.value,
                        task_queue.c.lease_expires_at <= database_now,
                    ),
                ),
            )
            .order_by(task_queue.c.available_at, task_queue.c.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
            .cte("claimable_task")
        )
        statement = (
            update(task_queue)
            .where(task_queue.c.id == candidate.c.id)
            .values(
                status=TaskStatus.RUNNING.value,
                attempts=task_queue.c.attempts + 1,
                locked_at=database_now,
                lease_expires_at=database_now + timedelta(seconds=lease_seconds),
                locked_by=worker_id,
                lease_token=lease_token,
                last_error=None,
                updated_at=database_now,
                completed_at=None,
            )
            .returning(*task_queue.c)
        )

        with self._engine.begin() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return None if row is None else TaskRecord.from_mapping(row)

    def succeed(self, task: TaskRecord) -> TaskRecord:
        lease_token = _require_lease(task)
        database_now = func.now()
        statement = (
            update(task_queue)
            .where(
                task_queue.c.id == task.id,
                task_queue.c.status == TaskStatus.RUNNING.value,
                task_queue.c.locked_by == task.locked_by,
                task_queue.c.lease_token == lease_token,
                task_queue.c.lease_expires_at > database_now,
            )
            .values(
                status=TaskStatus.SUCCEEDED.value,
                locked_at=None,
                lease_expires_at=None,
                locked_by=None,
                lease_token=None,
                last_error=None,
                updated_at=database_now,
                completed_at=database_now,
            )
            .returning(*task_queue.c)
        )
        return self._execute_lease_update(statement)

    def fail(
        self,
        task: TaskRecord,
        error: BaseException | str,
        *,
        retry_delay_seconds: int,
    ) -> TaskRecord:
        lease_token = _require_lease(task)
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must not be negative")

        database_now = func.now()
        sanitized_error = redact_text(str(error))[:MAX_ERROR_LENGTH]
        should_retry = task.attempts < task.max_attempts
        status = TaskStatus.PENDING if should_retry else TaskStatus.FAILED
        statement = (
            update(task_queue)
            .where(
                task_queue.c.id == task.id,
                task_queue.c.status == TaskStatus.RUNNING.value,
                task_queue.c.locked_by == task.locked_by,
                task_queue.c.lease_token == lease_token,
                task_queue.c.lease_expires_at > database_now,
            )
            .values(
                status=status.value,
                available_at=(
                    database_now + timedelta(seconds=retry_delay_seconds)
                    if should_retry
                    else task.available_at
                ),
                locked_at=None,
                lease_expires_at=None,
                locked_by=None,
                lease_token=None,
                last_error=sanitized_error,
                updated_at=database_now,
                completed_at=None if should_retry else database_now,
            )
            .returning(*task_queue.c)
        )
        return self._execute_lease_update(statement)

    def renew(self, task: TaskRecord, *, lease_seconds: int) -> TaskRecord:
        lease_token = _require_lease(task)
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        database_now = func.now()
        statement = (
            update(task_queue)
            .where(
                task_queue.c.id == task.id,
                task_queue.c.status == TaskStatus.RUNNING.value,
                task_queue.c.locked_by == task.locked_by,
                task_queue.c.lease_token == lease_token,
                task_queue.c.lease_expires_at > database_now,
            )
            .values(
                lease_expires_at=database_now + timedelta(seconds=lease_seconds),
                updated_at=database_now,
            )
            .returning(*task_queue.c)
        )
        return self._execute_lease_update(statement)

    def recover_exhausted_leases(self) -> int:
        database_now = func.now()
        statement = (
            update(task_queue)
            .where(
                task_queue.c.status == TaskStatus.RUNNING.value,
                task_queue.c.lease_expires_at <= database_now,
                task_queue.c.attempts >= task_queue.c.max_attempts,
            )
            .values(
                status=TaskStatus.FAILED.value,
                locked_at=None,
                lease_expires_at=None,
                locked_by=None,
                lease_token=None,
                last_error="task lease expired after maximum attempts",
                updated_at=database_now,
                completed_at=database_now,
            )
        )
        with self._engine.begin() as connection:
            result = connection.execute(statement)
        return result.rowcount or 0

    def get(self, task_id: UUID) -> TaskRecord | None:
        statement = select(task_queue).where(task_queue.c.id == task_id)
        with self._engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return None if row is None else TaskRecord.from_mapping(row)

    def purge_all(self) -> None:
        """Delete all tasks. Intended only for disposable tests."""

        with self._engine.begin() as connection:
            connection.execute(delete(task_queue))

    def _execute_lease_update(self, statement: Any) -> TaskRecord:
        with self._engine.begin() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            raise LostLeaseError("task lease is no longer owned by this worker")
        return TaskRecord.from_mapping(row)


def _require_lease(task: TaskRecord) -> UUID:
    if task.status is not TaskStatus.RUNNING or task.lease_token is None:
        raise LostLeaseError("task does not contain an active lease")
    return task.lease_token
