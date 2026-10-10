from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    FinancialAccountRecord,
    FinancialAccountStatus,
    FinancialAccountType,
    FinancialCashFlowAccountInput,
    FinancialCashFlowSource,
    FinancialCashFlowWindow,
    FinancialVisibilityScope,
    Money,
    new_financial_resource_id,
)
from meufinanceiro_persistence.financial_cash_flow_store import (
    FinancialCashFlowLimitExceededError,
    FinancialCashFlowPersistenceError,
)

import meufinanceiro_finance.cash_flow as cash_flow_module
from app.services.financial_cash_flow import (
    CashFlowRequestError,
    FinancialCashFlowService,
)

TODAY = date(2026, 10, 10)
NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)


def _account() -> FinancialAccountRecord:
    return FinancialAccountRecord(
        id=new_financial_resource_id(),
        residence_id=uuid4(),
        owner_operator_id=uuid4(),
        visibility_scope=FinancialVisibilityScope.PERSONAL,
        account_type=FinancialAccountType.CHECKING,
        custom_type_name=None,
        name="Conta",
        currency="BRL",
        status=FinancialAccountStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
        archived_at=None,
    )


class _Store:
    def __init__(self, *, reference_net: str = "0") -> None:
        self.calls: list[dict[str, Any]] = []
        self._reference_net = reference_net

    def read_source(self, **kwargs: Any) -> FinancialCashFlowSource:
        self.calls.append(kwargs)
        return FinancialCashFlowSource(
            accounts=(
                FinancialCashFlowAccountInput(
                    account=_account(),
                    opening_balance=None,
                    net_before_window=Money(Decimal(0), "BRL"),
                    net_through_reference=Money(Decimal(self._reference_net), "BRL"),
                ),
            ),
            movements=(),
            transfer_ids={},
            realized_occurrences={},
            pending_occurrences=(),
            live_occurrence_months=frozenset(),
            rules=(),
        )


def _scope() -> dict[str, UUID]:
    return {"installation_id": uuid4(), "residence_id": uuid4(), "operator_id": uuid4()}


def _read(service: FinancialCashFlowService, **overrides: Any) -> Any:
    values: dict[str, Any] = {
        "from_date": None,
        "through_date": None,
        "account_ids": None,
        "currency": None,
    }
    values.update(overrides)
    return service.read_cash_flow(**_scope(), **values)


def test_defaults_come_from_the_injected_clock_and_are_forwarded() -> None:
    store = _Store()
    service = FinancialCashFlowService(store, clock=lambda: TODAY, instant=lambda: NOW)

    projection = _read(service, currency="BRL")

    window = store.calls[0]["window"]
    assert window == FinancialCashFlowWindow(TODAY, date(2026, 11, 8), TODAY)
    assert store.calls[0]["currency"] == "BRL"
    assert store.calls[0]["account_ids"] is None
    assert projection.calculated_at == NOW
    assert projection.window.reference_date == TODAY


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2026, 10, 11), None),
        (TODAY, date(2026, 10, 9)),
        (TODAY, date(2027, 1, 10)),
    ],
)
def test_invalid_windows_never_reach_the_store(start: date, end: date | None) -> None:
    store = _Store()
    service = FinancialCashFlowService(store, clock=lambda: TODAY)
    with pytest.raises(CashFlowRequestError):
        _read(service, from_date=start, through_date=end)
    assert store.calls == []


def test_inconsistent_source_is_a_sanitized_persistence_error() -> None:
    service = FinancialCashFlowService(_Store(reference_net="5"), clock=lambda: TODAY)
    with pytest.raises(FinancialCashFlowPersistenceError):
        _read(service)


def test_domain_event_limit_maps_to_the_limit_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cash_flow_module, "CASH_FLOW_EVENTS_MAX", -1)
    service = FinancialCashFlowService(_Store(), clock=lambda: TODAY)
    with pytest.raises(FinancialCashFlowLimitExceededError):
        _read(service)


def test_store_must_satisfy_the_boundary() -> None:
    with pytest.raises(TypeError):
        FinancialCashFlowService(object(), clock=lambda: TODAY)  # type: ignore[arg-type]


def test_clock_must_return_a_plain_date() -> None:
    service = FinancialCashFlowService(_Store(), clock=lambda: NOW)
    with pytest.raises(TypeError):
        _read(service)
