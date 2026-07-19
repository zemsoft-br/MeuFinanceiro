from __future__ import annotations

import json
import logging
import os
import signal
import socket
import threading
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

from meufinanceiro_persistence import (
    Database,
    LostLeaseError,
    TaskQueue,
    TaskRecord,
)
from meufinanceiro_persistence.health import inspect_persistence_health
from meufinanceiro_persistence.schema import demo_task_effects
from meufinanceiro_security.keyring import load_keyring
from meufinanceiro_security.redaction import install_log_redaction
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import SQLAlchemyError


class Settings(BaseSettings):
    database_url: SecretStr
    app_keyring_file: Path = Path("/run/secrets/app_keyring")
    worker_health_port: int = 8081
    worker_poll_interval_seconds: float = 1.0
    worker_lease_seconds: int = 30
    worker_retry_base_seconds: int = 2
    worker_retry_max_seconds: int = 60
    app_log_level: str = "INFO"

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")


logger = logging.getLogger("meufinanceiro.worker")
stop_event = threading.Event()
TaskHandler = Callable[[Database, TaskRecord], None]


def handle_demo_echo(database: Database, task: TaskRecord) -> None:
    message = str(task.payload.get("message", ""))[:500]
    statement = (
        postgresql_insert(demo_task_effects)
        .values(task_id=task.id, message=message)
        .on_conflict_do_nothing(index_elements=[demo_task_effects.c.task_id])
    )
    with database.engine.begin() as connection:
        connection.execute(statement)
    logger.info(
        "demo task handled task_id=%s correlation_id=%s",
        task.id,
        task.correlation_id,
    )


HANDLERS: dict[str, TaskHandler] = {"demo.echo": handle_demo_echo}


def retry_delay(task: TaskRecord, settings: Settings) -> int:
    exponent = max(task.attempts - 1, 0)
    delay = settings.worker_retry_base_seconds
    for _ in range(exponent):
        delay *= 2
    return min(delay, settings.worker_retry_max_seconds)


def build_health_handler(database: Database) -> type[BaseHTTPRequestHandler]:
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib contract
            if self.path not in {"/health/live", "/health/ready"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            if self.path == "/health/live":
                status = HTTPStatus.OK
                body: dict[str, Any] = {
                    "status": "ok",
                    "service": "worker",
                    "process": "ok",
                }
            else:
                persistence = inspect_persistence_health(database.engine)
                status = (
                    HTTPStatus.OK
                    if persistence.ready
                    else HTTPStatus.SERVICE_UNAVAILABLE
                )
                body = {
                    "status": "ok" if persistence.ready else "degraded",
                    "service": "worker",
                    "process": "ok",
                    "database": persistence.database,
                    "schema": persistence.schema,
                    "current_revision": persistence.current_revision,
                    "expected_revision": persistence.expected_revision,
                }

            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            return

    return HealthHandler


def request_shutdown(signum: int, _frame: object) -> None:
    logger.info("shutdown requested signal=%s", signum)
    stop_event.set()


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid4()}"


def run_worker(settings: Settings) -> None:
    load_keyring(settings.app_keyring_file)
    database = Database(settings.database_url.get_secret_value())
    queue = TaskQueue(database.engine)
    worker_id = worker_identity()
    health_server = ThreadingHTTPServer(
        ("0.0.0.0", settings.worker_health_port),
        build_health_handler(database),
    )
    health_thread = threading.Thread(
        target=health_server.serve_forever,
        name="worker-health",
        daemon=True,
    )
    health_thread.start()
    logger.info(
        "worker started worker_id=%s health_port=%s",
        worker_id,
        settings.worker_health_port,
    )

    try:
        while not stop_event.is_set():
            try:
                queue.recover_exhausted_leases()
                task = queue.claim(
                    worker_id=worker_id,
                    lease_seconds=settings.worker_lease_seconds,
                )
            except SQLAlchemyError:
                logger.exception("database unavailable while polling tasks")
                stop_event.wait(settings.worker_poll_interval_seconds)
                continue

            if task is None:
                stop_event.wait(settings.worker_poll_interval_seconds)
                continue

            try:
                handler = HANDLERS[task.task_type]
                handler(database, task)
            except Exception as exc:
                try:
                    failed = queue.fail(
                        task,
                        exc,
                        retry_delay_seconds=retry_delay(task, settings),
                    )
                except LostLeaseError:
                    logger.warning(
                        "task failure ignored after lease loss task_id=%s",
                        task.id,
                    )
                except SQLAlchemyError:
                    logger.exception(
                        "task failure could not be persisted task_id=%s",
                        task.id,
                    )
                else:
                    logger.error(
                        "task failed task_id=%s status=%s attempts=%s",
                        failed.id,
                        failed.status.value,
                        failed.attempts,
                        exc_info=(type(exc), exc, exc.__traceback__),
                    )
            else:
                try:
                    completed = queue.succeed(task)
                except LostLeaseError:
                    logger.warning(
                        "task completion ignored after lease loss task_id=%s",
                        task.id,
                    )
                except SQLAlchemyError:
                    logger.exception(
                        "task completion could not be persisted task_id=%s",
                        task.id,
                    )
                else:
                    logger.info(
                        "task succeeded task_id=%s attempts=%s",
                        completed.id,
                        completed.attempts,
                    )
    finally:
        health_server.shutdown()
        health_server.server_close()
        health_thread.join(timeout=5)
        database.dispose()
        logger.info("worker stopped")


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    logging.basicConfig(
        level=getattr(logging, settings.app_log_level.upper(), logging.INFO),
        format=(
            '{"timestamp":"%(asctime)s","level":"%(levelname)s",'
            '"service":"worker","message":"%(message)s"}'
        ),
    )
    install_log_redaction()
    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    run_worker(settings)


if __name__ == "__main__":
    main()
