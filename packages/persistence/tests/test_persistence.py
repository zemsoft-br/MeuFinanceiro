from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import Engine, func, select, update

from meufinanceiro_persistence import (
    LostLeaseError,
    TaskQueue,
    TaskRecord,
    TaskStatus,
)
from meufinanceiro_persistence.bootstrap import (
    bootstrap_runtime_role,
    normalize_psycopg_url,
)
from meufinanceiro_persistence.database import Database
from meufinanceiro_persistence.health import inspect_persistence_health
from meufinanceiro_persistence.migrations import downgrade_to_base, upgrade
from meufinanceiro_persistence.schema import demo_task_effects, task_queue
from meufinanceiro_persistence.settings import BootstrapSettings


def test_00_initial_migration_round_trip(
    database_url: str,
    app_database_user: str,
    engine: Engine,
) -> None:
    engine.dispose()
    downgrade_to_base(database_url, app_database_user=app_database_user)
    upgrade(database_url, app_database_user=app_database_user)

    health = inspect_persistence_health(engine)
    assert health.ready
    assert health.current_revision == health.expected_revision


def test_bootstrap_rejects_administrative_role_as_runtime_role(
    database_url: str,
) -> None:
    with psycopg.connect(normalize_psycopg_url(database_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user")
            administrative_row = cursor.fetchone()
            assert administrative_row is not None
            administrative_role = administrative_row[0]

    settings = BootstrapSettings(
        admin_database_url=database_url,
        app_database_user=administrative_role,
        app_database_password="disposable-test-password",
    )

    with pytest.raises(
        ValueError,
        match="must differ from the administrative database role",
    ):
        bootstrap_runtime_role(settings)


def test_database_transaction_commits_and_rolls_back(
    database_url: str,
    engine: Engine,
) -> None:
    database = Database(database_url)
    queue = TaskQueue(database.engine)
    try:
        with database.transaction() as session:
            session.execute(
                task_queue.insert().values(
                    id=uuid4(),
                    task_type="demo.echo",
                    payload={},
                    status="pending",
                    idempotency_key="transaction-commit",
                    correlation_id=uuid4(),
                    attempts=0,
                    max_attempts=3,
                    available_at=datetime.now(timezone.utc),
                    locked_at=None,
                    lease_expires_at=None,
                    locked_by=None,
                    lease_token=None,
                    last_error=None,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                    completed_at=None,
                )
            )
        assert (
            queue.enqueue(
                task_type="demo.echo",
                payload={},
                idempotency_key="transaction-commit",
            ).idempotency_key
            == "transaction-commit"
        )

        with pytest.raises(RuntimeError, match="rollback"):
            with database.transaction() as session:
                session.execute(
                    task_queue.insert().values(
                        id=uuid4(),
                        task_type="demo.echo",
                        payload={},
                        status="pending",
                        idempotency_key="transaction-rollback",
                        correlation_id=uuid4(),
                        attempts=0,
                        max_attempts=3,
                        available_at=datetime.now(timezone.utc),
                        locked_at=None,
                        lease_expires_at=None,
                        locked_by=None,
                        lease_token=None,
                        last_error=None,
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                        completed_at=None,
                    )
                )
                raise RuntimeError("rollback")

        with engine.connect() as connection:
            count = connection.scalar(
                select(func.count())
                .select_from(task_queue)
                .where(task_queue.c.idempotency_key == "transaction-rollback")
            )
        assert count == 0
    finally:
        database.dispose()


def test_enqueue_is_idempotent(engine: Engine) -> None:
    queue = TaskQueue(engine)

    first = queue.enqueue(
        task_type="demo.echo",
        payload={"value": 1},
        idempotency_key="same-effect",
    )
    second = queue.enqueue(
        task_type="demo.echo",
        payload={"value": 2},
        idempotency_key="same-effect",
    )

    assert second.id == first.id
    assert second.payload == {"value": 1}
    with engine.connect() as connection:
        count = connection.scalar(select(func.count()).select_from(task_queue))
    assert count == 1


def test_concurrent_enqueue_returns_one_task(engine: Engine) -> None:
    barrier = Barrier(2)

    def enqueue(value: int) -> TaskRecord:
        barrier.wait()
        return TaskQueue(engine).enqueue(
            task_type="demo.echo",
            payload={"value": value},
            idempotency_key="concurrent-idempotency",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.map(enqueue, (1, 2))

    assert first.id == second.id
    with engine.connect() as connection:
        count = connection.scalar(select(func.count()).select_from(task_queue))
    assert count == 1


def test_pending_task_survives_engine_restart(
    database_url: str,
    engine: Engine,
) -> None:
    queued = TaskQueue(engine).enqueue(
        task_type="demo.echo",
        payload={"message": "persisted"},
        idempotency_key="survives-restart",
    )
    engine.dispose()

    restarted = Database(database_url)
    try:
        recovered = TaskQueue(restarted.engine).get(queued.id)
    finally:
        restarted.dispose()

    assert recovered is not None
    assert recovered.status is TaskStatus.PENDING
    assert recovered.payload == {"message": "persisted"}


def test_two_workers_do_not_claim_the_same_task(engine: Engine) -> None:
    queue = TaskQueue(engine)
    queued = queue.enqueue(
        task_type="demo.echo",
        payload={},
        idempotency_key="concurrent-claim",
    )
    barrier = Barrier(2)

    def claim(worker_id: str) -> object:
        barrier.wait()
        return TaskQueue(engine).claim(worker_id=worker_id, lease_seconds=30)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ("worker-a", "worker-b")))

    claimed = [task for task in results if task is not None]
    assert len(claimed) == 1
    assert claimed[0].id == queued.id


def test_expired_lease_is_reclaimed_with_a_new_token(engine: Engine) -> None:
    queue = TaskQueue(engine)
    queued = queue.enqueue(
        task_type="demo.echo",
        payload={},
        idempotency_key="expired-lease",
        max_attempts=3,
    )
    first = queue.claim(worker_id="worker-a", lease_seconds=30)
    assert first is not None

    with engine.begin() as connection:
        connection.execute(
            update(task_queue)
            .where(task_queue.c.id == queued.id)
            .values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        )

    second = queue.claim(worker_id="worker-b", lease_seconds=30)
    assert second is not None
    assert second.id == queued.id
    assert second.attempts == 2
    assert second.lease_token != first.lease_token

    with pytest.raises(LostLeaseError):
        queue.succeed(first)


def test_exhausted_expired_lease_becomes_auditable_failure(engine: Engine) -> None:
    queue = TaskQueue(engine)
    queued = queue.enqueue(
        task_type="demo.echo",
        payload={},
        idempotency_key="exhausted-lease",
        max_attempts=1,
    )
    claimed = queue.claim(worker_id="worker-a", lease_seconds=30)
    assert claimed is not None

    with engine.begin() as connection:
        connection.execute(
            update(task_queue)
            .where(task_queue.c.id == queued.id)
            .values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        )

    assert queue.recover_exhausted_leases() == 1
    failed = queue.get(queued.id)
    assert failed is not None
    assert failed.status is TaskStatus.FAILED
    assert failed.completed_at is not None
    assert failed.last_error == "task lease expired after maximum attempts"


def test_retry_error_is_redacted_and_eventually_terminal(engine: Engine) -> None:
    queue = TaskQueue(engine)
    task = queue.enqueue(
        task_type="demo.echo",
        payload={},
        idempotency_key="retry",
        max_attempts=2,
    )

    first = queue.claim(worker_id="worker-a", lease_seconds=30)
    assert first is not None
    retried = queue.fail(
        first,
        "database_url=postgresql://user:secret@example/db token=abc123",
        retry_delay_seconds=0,
    )
    assert retried.status is TaskStatus.PENDING
    assert "secret" not in (retried.last_error or "")
    assert "abc123" not in (retried.last_error or "")

    second = queue.claim(worker_id="worker-a", lease_seconds=30)
    assert second is not None
    failed = queue.fail(second, "final failure", retry_delay_seconds=0)
    assert failed.status is TaskStatus.FAILED
    assert failed.completed_at is not None
    assert queue.get(task.id) == failed


def test_demo_effect_is_unique_per_task(engine: Engine) -> None:
    from worker.main import handle_demo_echo

    queue = TaskQueue(engine)
    task = queue.enqueue(
        task_type="demo.echo",
        payload={"message": "hello"},
        idempotency_key="demo-effect",
    )
    claimed = queue.claim(worker_id="worker-a", lease_seconds=30)
    assert claimed is not None
    database = Database(engine.url.render_as_string(hide_password=False))
    try:
        handle_demo_echo(database, claimed)
        handle_demo_echo(database, claimed)
    finally:
        database.dispose()

    with engine.connect() as connection:
        count = connection.scalar(select(func.count()).select_from(demo_task_effects))
    assert count == 1
    assert task.id == claimed.id
