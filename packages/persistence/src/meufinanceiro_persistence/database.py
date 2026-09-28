"""Database engine and explicit transaction boundaries."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker


class Database:
    """Own a SQLAlchemy engine and short-lived transactional sessions."""

    def __init__(
        self,
        database_url: str,
        *,
        pool_size: int = 5,
        max_overflow: int = 5,
    ) -> None:
        engine_options: dict[str, Any] = {"pool_pre_ping": True}
        if not database_url.startswith("sqlite"):
            engine_options.update(
                pool_size=pool_size,
                max_overflow=max_overflow,
            )
        self.engine: Engine = create_engine(database_url, **engine_options)
        self._session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            autoflush=False,
        )

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Open one transaction that commits or rolls back as a unit."""

        with self._session_factory.begin() as session:
            yield session

    def ping(self) -> None:
        """Verify that a real database round-trip succeeds."""

        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def dispose(self) -> None:
        self.engine.dispose()
