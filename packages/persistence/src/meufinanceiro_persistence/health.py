"""Database and schema readiness probes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from meufinanceiro_persistence.migrations import current_revision, expected_revision

DatabaseState = Literal["ok", "unavailable"]
SchemaState = Literal["ok", "outdated", "unavailable"]


@dataclass(frozen=True, slots=True)
class PersistenceHealth:
    database: DatabaseState
    schema: SchemaState
    current_revision: str | None
    expected_revision: str

    @property
    def ready(self) -> bool:
        return self.database == "ok" and self.schema == "ok"


def inspect_persistence_health(engine: Engine) -> PersistenceHealth:
    expected = expected_revision()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return PersistenceHealth(
            database="unavailable",
            schema="unavailable",
            current_revision=None,
            expected_revision=expected,
        )

    try:
        current = current_revision(engine)
    except SQLAlchemyError:
        return PersistenceHealth(
            database="ok",
            schema="unavailable",
            current_revision=None,
            expected_revision=expected,
        )

    return PersistenceHealth(
        database="ok",
        schema="ok" if current == expected else "outdated",
        current_revision=current,
        expected_revision=expected,
    )
