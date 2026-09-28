"""Deterministic lifecycle for the isolated residencia-ipe demonstration fixture."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import Engine, delete, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError

from meufinanceiro_persistence.demo_contract import (
    DEMO_CONTRACT_CHECKSUM,
    DEMO_CURRENCY,
    DEMO_FIXTURE_ID,
    DEMO_FIXTURE_VERSION,
    DEMO_REFERENCE_DATE,
    DEMO_SCOPE,
    DEMO_TIMEZONE,
)
from meufinanceiro_persistence.demo_financial_fixture import (
    DemoFinancialFixtureConflictError,
    demo_functional_rows_exist,
    load_demo_financial_fixture,
    reset_demo_financial_fixture,
    verify_demo_financial_fixture,
)
from meufinanceiro_persistence.schema import demo_fixture


class DemoModeDisabledError(RuntimeError):
    """Raised when a mutating demo command runs outside demo mode."""


class DemoFixtureConflictError(RuntimeError):
    """Raised when persisted demo state disagrees with the canonical fixture."""


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
    """Load, inspect and reset the versioned synthetic demo dataset."""

    def __init__(
        self,
        engine: Engine,
        *,
        enabled: bool,
        operator_password: str | None = None,
        reset_engine: Engine | None = None,
    ) -> None:
        self._engine = engine
        self._enabled = enabled
        self._operator_password = operator_password
        self._reset_engine = reset_engine

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise DemoModeDisabledError("demo mode is not enabled")

    def _require_operator_password(self) -> str:
        value = self._operator_password
        if not isinstance(value, str) or not value:
            raise DemoFixtureConflictError("demo operator credential is not configured")
        return value

    def _require_reset_engine(self) -> Engine:
        if self._reset_engine is None:
            raise DemoFixtureConflictError(
                "demo administrative reset is not configured"
            )
        return self._reset_engine

    def status(self) -> DemoFixtureStatus:
        if not self._enabled:
            return unloaded_demo_status(enabled=False)

        try:
            with self._engine.begin() as connection:
                row = (
                    connection.execute(
                        select(demo_fixture).where(
                            demo_fixture.c.fixture_id == DEMO_FIXTURE_ID
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    if demo_functional_rows_exist(connection):
                        raise DemoFixtureConflictError(
                            "demo functional rows exist without fixture metadata"
                        )
                    return unloaded_demo_status(enabled=True)
                status = self._validated_status(row)
                verify_demo_financial_fixture(connection)
                return status
        except DemoFixtureConflictError:
            raise
        except DemoFinancialFixtureConflictError as exc:
            raise DemoFixtureConflictError(str(exc)) from None
        except DBAPIError:
            raise DemoFixtureConflictError(
                "demo fixture could not be inspected"
            ) from None

    def load(self) -> DemoFixtureStatus:
        self._require_enabled()
        operator_password = self._require_operator_password()
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
                loaded_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(index_elements=[demo_fixture.c.fixture_id])
        )
        try:
            with self._engine.begin() as connection:
                connection.execute(statement)
                row = (
                    connection.execute(
                        select(demo_fixture).where(
                            demo_fixture.c.fixture_id == DEMO_FIXTURE_ID
                        )
                    )
                    .mappings()
                    .one()
                )
                status = self._validated_status(row)
                load_demo_financial_fixture(
                    connection,
                    operator_password=operator_password,
                )
                verify_demo_financial_fixture(connection)
                return status
        except DemoFixtureConflictError:
            raise
        except DemoFinancialFixtureConflictError as exc:
            raise DemoFixtureConflictError(str(exc)) from None
        except (IntegrityError, DBAPIError):
            raise DemoFixtureConflictError(
                "demo fixture could not be materialized"
            ) from None

    def reset(self) -> bool:
        self._require_enabled()
        reset_engine = self._require_reset_engine()
        try:
            with reset_engine.begin() as connection:
                changed = reset_demo_financial_fixture(connection)
                result = connection.execute(
                    delete(demo_fixture).where(
                        demo_fixture.c.fixture_id == DEMO_FIXTURE_ID
                    )
                )
                return changed or bool(result.rowcount)
        except DBAPIError:
            raise DemoFixtureConflictError("demo fixture could not be reset") from None

    def _validated_status(self, row: RowMapping) -> DemoFixtureStatus:
        status = DemoFixtureStatus(
            enabled=True,
            loaded=True,
            fixture_id=row["fixture_id"],
            fixture_version=row["fixture_version"],
            reference_date=row["reference_date"],
            timezone=row["timezone"],
            currency=row["currency"],
            scope=row["scope"],
            contract_checksum=row["contract_checksum"],
            loaded_at=row["loaded_at"],
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
        if any(
            getattr(status, field) != getattr(expected, field) for field in comparable
        ):
            raise DemoFixtureConflictError(
                "persisted demo fixture metadata does not match the canonical contract"
            )
        return status
