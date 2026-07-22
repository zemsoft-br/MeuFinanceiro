"""Deterministic metadata contract for the isolated demonstration environment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Final

from sqlalchemy import Engine, delete, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from meufinanceiro_persistence.schema import demo_fixture

DEMO_FIXTURE_ID: Final = "residencia-ipe-v1"
DEMO_FIXTURE_VERSION: Final = 1
DEMO_REFERENCE_DATE: Final = date(2026, 11, 1)
DEMO_TIMEZONE: Final = "America/Sao_Paulo"
DEMO_CURRENCY: Final = "BRL"
DEMO_SCOPE: Final = "foundation_only"
DEMO_CONTRACT_CHECKSUM: Final = (
    "34a7628233ff6c4f5eac6469b8e80fdedd5d65d80f825b4ecf72a069235a21a1"
)


class DemoModeDisabledError(RuntimeError):
    """Raised when a mutating demo command runs outside demo mode."""


class DemoFixtureConflictError(RuntimeError):
    """Raised when persisted metadata disagrees with the canonical fixture."""


@dataclass(frozen=True)
class DemoFixtureStatus:
    enabled: bool
    loaded: bool
    fixture_id: str
    fixture_version: int
    reference_date: date
    timezone: str
    currency: str
    scope: str
    contract_checksum: str
    loaded_at: datetime | None = None


def unloaded_demo_status(*, enabled: bool) -> DemoFixtureStatus:
    return DemoFixtureStatus(
        enabled=enabled,
        loaded=False,
        fixture_id=DEMO_FIXTURE_ID,
        fixture_version=DEMO_FIXTURE_VERSION,
        reference_date=DEMO_REFERENCE_DATE,
        timezone=DEMO_TIMEZONE,
        currency=DEMO_CURRENCY,
        scope=DEMO_SCOPE,
        contract_checksum=DEMO_CONTRACT_CHECKSUM,
    )


class DemoFixtureStore:
    """Load, inspect and reset only the canonical demo metadata row."""

    def __init__(self, engine: Engine, *, enabled: bool) -> None:
        self._engine = engine
        self._enabled = enabled

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise DemoModeDisabledError("demo mode is not enabled")

    def status(self) -> DemoFixtureStatus:
        if not self._enabled:
            return unloaded_demo_status(enabled=False)

        with self._engine.connect() as connection:
            row = connection.execute(
                select(demo_fixture).where(
                    demo_fixture.c.fixture_id == DEMO_FIXTURE_ID
                )
            ).mappings().one_or_none()
        if row is None:
            return unloaded_demo_status(enabled=True)
        return self._validated_status(row)

    def load(self) -> DemoFixtureStatus:
        self._require_enabled()
        loaded_at = datetime.now(timezone.utc)
        statement = (
            postgresql_insert(demo_fixture)
            .values(
                fixture_id=DEMO_FIXTURE_ID,
                fixture_version=DEMO_FIXTURE_VERSION,
                reference_date=DEMO_REFERENCE_DATE,
                timezone=DEMO_TIMEZONE,
                currency=DEMO_CURRENCY,
                scope=DEMO_SCOPE,
                contract_checksum=DEMO_CONTRACT_CHECKSUM,
                loaded_at=loaded_at,
            )
            .on_conflict_do_nothing(index_elements=[demo_fixture.c.fixture_id])
        )
        with self._engine.begin() as connection:
            connection.execute(statement)
            row = connection.execute(
                select(demo_fixture).where(
                    demo_fixture.c.fixture_id == DEMO_FIXTURE_ID
                )
            ).mappings().one()
        return self._validated_status(row)

    def reset(self) -> bool:
        self._require_enabled()
        with self._engine.begin() as connection:
            result = connection.execute(
                delete(demo_fixture).where(
                    demo_fixture.c.fixture_id == DEMO_FIXTURE_ID
                )
            )
        return bool(result.rowcount)

    def _validated_status(self, row: object) -> DemoFixtureStatus:
        mapping = row
        status = DemoFixtureStatus(
            enabled=True,
            loaded=True,
            fixture_id=mapping["fixture_id"],  # type: ignore[index]
            fixture_version=mapping["fixture_version"],  # type: ignore[index]
            reference_date=mapping["reference_date"],  # type: ignore[index]
            timezone=mapping["timezone"],  # type: ignore[index]
            currency=mapping["currency"],  # type: ignore[index]
            scope=mapping["scope"],  # type: ignore[index]
            contract_checksum=mapping["contract_checksum"],  # type: ignore[index]
            loaded_at=mapping["loaded_at"],  # type: ignore[index]
        )
        expected = unloaded_demo_status(enabled=True)
        comparable = (
            "fixture_id",
            "fixture_version",
            "reference_date",
            "timezone",
            "currency",
            "scope",
            "contract_checksum",
        )
        if any(getattr(status, field) != getattr(expected, field) for field in comparable):
            raise DemoFixtureConflictError(
                "persisted demo fixture metadata does not match the canonical contract"
            )
        return status
