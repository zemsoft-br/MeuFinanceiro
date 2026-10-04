from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from meufinanceiro_persistence.financial_movement_allocation_store import (
    FinancialMovementAllocationNotFoundError,
)
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementNotFoundError,
)

from app.services.financial_core import FinancialCoreService

INSTALLATION_ID = UUID("10000000-0000-4000-8000-000000000001")
RESIDENCE_ID = UUID("20000000-0000-4000-8000-000000000002")
OPERATOR_ID = UUID("30000000-0000-4000-8000-000000000003")
MOVEMENT_ID = UUID("60000000-0000-4000-8000-000000000006")
ACCOUNT_ID = UUID("40000000-0000-4000-8000-000000000004")
KEY = UUID("f7000000-0000-4000-8000-0000000000f7")
SCOPE = {
    "installation_id": INSTALLATION_ID,
    "residence_id": RESIDENCE_ID,
    "operator_id": OPERATOR_ID,
}

_ACCOUNT = ("create_account", "list_accounts", "get_account")
_OPENING = ("create_opening_balance", "get_opening_balance")
_MOVEMENT = ("create_movement", "reverse_movement", "get_movement", "list_movements")
_TRANSFER = ("create_transfer", "reverse_transfer", "list_transfers")
_BALANCE = ("get_balance_snapshot", "get_statement")
_CATEGORY = ("create_category", "list_categories")
_ALLOCATION = (
    "create_allocation_set",
    "revise_allocation_set",
    "get_current_allocation_set",
    "list_current_allocation_sets",
)


class Recorder:
    """Callable stub that records calls and returns/raises a configured outcome."""

    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result = result
        self.error = error

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


def _store(names: tuple[str, ...], **overrides: Recorder) -> SimpleNamespace:
    return SimpleNamespace(**{name: overrides.get(name, Recorder()) for name in names})


def _service(
    *,
    movements: SimpleNamespace | None = None,
    categories: SimpleNamespace | None = None,
    allocations: SimpleNamespace | None = None,
) -> FinancialCoreService:
    return FinancialCoreService(
        _store(_ACCOUNT),  # type: ignore[arg-type]
        _store(_OPENING),  # type: ignore[arg-type]
        movements or _store(_MOVEMENT),  # type: ignore[arg-type]
        _store(_TRANSFER),  # type: ignore[arg-type]
        _store(_BALANCE),  # type: ignore[arg-type]
        categories or _store(_CATEGORY),  # type: ignore[arg-type]
        allocations or _store(_ALLOCATION),  # type: ignore[arg-type]
    )


def test_service_refuses_stores_that_do_not_satisfy_the_new_boundaries() -> None:
    with pytest.raises(TypeError, match="category_store"):
        FinancialCoreService(
            _store(_ACCOUNT),  # type: ignore[arg-type]
            _store(_OPENING),  # type: ignore[arg-type]
            _store(_MOVEMENT),  # type: ignore[arg-type]
            _store(_TRANSFER),  # type: ignore[arg-type]
            _store(_BALANCE),  # type: ignore[arg-type]
            _store(("create_category",)),  # type: ignore[arg-type]
            _store(_ALLOCATION),  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="allocation_store"):
        FinancialCoreService(
            _store(_ACCOUNT),  # type: ignore[arg-type]
            _store(_OPENING),  # type: ignore[arg-type]
            _store(_MOVEMENT),  # type: ignore[arg-type]
            _store(_TRANSFER),  # type: ignore[arg-type]
            _store(_BALANCE),  # type: ignore[arg-type]
            _store(_CATEGORY),  # type: ignore[arg-type]
            _store(("create_allocation_set", "revise_allocation_set")),  # type: ignore[arg-type]
        )


def test_current_allocation_is_none_for_accessible_unclassified_movement() -> None:
    get_movement = Recorder(result=object())
    get_current = Recorder(error=FinancialMovementAllocationNotFoundError("none"))
    service = _service(
        movements=_store(_MOVEMENT, get_movement=get_movement),
        allocations=_store(_ALLOCATION, get_current_allocation_set=get_current),
    )

    assert service.get_current_allocation(**SCOPE, movement_id=MOVEMENT_ID) is None
    assert get_movement.calls == [{**SCOPE, "movement_id": MOVEMENT_ID}]
    assert get_current.calls == [{**SCOPE, "movement_id": MOVEMENT_ID}]


def test_missing_movement_is_not_reported_as_unclassified() -> None:
    get_movement = Recorder(error=FinancialMovementNotFoundError("missing"))
    get_current = Recorder()
    service = _service(
        movements=_store(_MOVEMENT, get_movement=get_movement),
        allocations=_store(_ALLOCATION, get_current_allocation_set=get_current),
    )

    with pytest.raises(FinancialMovementNotFoundError):
        service.get_current_allocation(**SCOPE, movement_id=MOVEMENT_ID)
    assert get_current.calls == []
