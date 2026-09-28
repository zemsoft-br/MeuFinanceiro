"""Small operational CLI for the foundation task queue."""

from __future__ import annotations

import argparse
import json
from uuid import uuid4

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from meufinanceiro_persistence.database import Database
from meufinanceiro_persistence.queue import TaskQueue


class CliSettings(BaseSettings):
    database_url: SecretStr

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("enqueue-demo", "get"))
    parser.add_argument("--task-id")
    parser.add_argument("--idempotency-key")
    args = parser.parse_args()

    settings = CliSettings()  # type: ignore[call-arg]
    database = Database(settings.database_url.get_secret_value())
    queue = TaskQueue(database.engine)
    try:
        if args.command == "enqueue-demo":
            key = args.idempotency_key or f"demo:{uuid4()}"
            enqueued = queue.enqueue(
                task_type="demo.echo",
                payload={"message": "foundation smoke task"},
                idempotency_key=key,
            )
            print(json.dumps({"id": str(enqueued.id), "status": enqueued.status.value}))
            return

        if not args.task_id:
            parser.error("--task-id is required for get")
        from uuid import UUID

        found = queue.get(UUID(args.task_id))
        if found is None:
            raise SystemExit(2)
        print(
            json.dumps(
                {
                    "id": str(found.id),
                    "status": found.status.value,
                    "attempts": found.attempts,
                    "last_error": found.last_error,
                }
            )
        )
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
