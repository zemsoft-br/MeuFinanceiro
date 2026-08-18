"""Public demo lifecycle with FK-safe administrative financial reset."""

from sqlalchemy import delete
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.demo_contract import DEMO_FIXTURE_ID
from meufinanceiro_persistence.demo_financial_extensions_cleanup import (
    reset_demo_financial_extensions,
)
from meufinanceiro_persistence.demo_financial_fixture import (
    reset_demo_financial_fixture,
)
from meufinanceiro_persistence.demo_store_base import (
    DemoFixtureConflictError,
    DemoFixtureStatus,
    DemoModeDisabledError,
    DemoFixtureStore as _BaseDemoFixtureStore,
    unloaded_demo_status,
)
from meufinanceiro_persistence.demo_transfer_cleanup import reset_demo_transfers
from meufinanceiro_persistence.schema import demo_fixture


class DemoFixtureStore(_BaseDemoFixtureStore):
    """Demo store with dependency-aware administrative cleanup."""

    def reset(self) -> bool:
        self._require_enabled()
        reset_engine = self._require_reset_engine()
        try:
            with reset_engine.begin() as connection:
                extension_changed = reset_demo_financial_extensions(connection)
                transfer_changed = reset_demo_transfers(connection)
                financial_changed = reset_demo_financial_fixture(connection)
                result = connection.execute(
                    delete(demo_fixture).where(
                        demo_fixture.c.fixture_id == DEMO_FIXTURE_ID
                    )
                )
                return (
                    extension_changed
                    or transfer_changed
                    or financial_changed
                    or bool(result.rowcount)
                )
        except DBAPIError:
            raise DemoFixtureConflictError("demo fixture could not be reset") from None


__all__ = [
    "DemoFixtureConflictError",
    "DemoFixtureStatus",
    "DemoFixtureStore",
    "DemoModeDisabledError",
    "unloaded_demo_status",
]
