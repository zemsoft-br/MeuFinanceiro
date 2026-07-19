import threading
from pathlib import Path
from uuid import uuid4

from meufinanceiro_persistence.queue import TaskRecord, TaskStatus

from worker.main import LeaseHeartbeat, Settings, retry_delay


def task(attempts: int) -> TaskRecord:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return TaskRecord(
        id=uuid4(),
        task_type="demo.echo",
        payload={},
        status=TaskStatus.RUNNING,
        idempotency_key="test",
        correlation_id=uuid4(),
        attempts=attempts,
        max_attempts=5,
        available_at=now,
        locked_at=now,
        lease_expires_at=now,
        locked_by="worker",
        lease_token=uuid4(),
        last_error=None,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )


def test_retry_delay_is_exponential_and_capped(tmp_path: Path) -> None:
    settings = Settings(
        database_url="postgresql+psycopg://example.invalid/db",
        app_keyring_file=tmp_path / "keyring.json",
        worker_retry_base_seconds=2,
        worker_retry_max_seconds=10,
    )

    assert retry_delay(task(1), settings) == 2
    assert retry_delay(task(2), settings) == 4
    assert retry_delay(task(4), settings) == 10


class RecordingQueue:
    def __init__(self) -> None:
        self.renewed = threading.Event()
        self.calls = 0

    def renew(self, task: TaskRecord, *, lease_seconds: int) -> TaskRecord:
        assert lease_seconds == 30
        self.calls += 1
        self.renewed.set()
        return task


def test_lease_heartbeat_renews_during_handler() -> None:
    queue = RecordingQueue()

    with LeaseHeartbeat(
        queue,  # type: ignore[arg-type]
        task(1),
        lease_seconds=30,
        interval_seconds=0.01,
    ):
        assert queue.renewed.wait(timeout=1)

    assert queue.calls >= 1
