from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    FinancialAccountStatus,
    FinancialGoalAccountInput,
    FinancialGoalAllocationDraft,
    FinancialGoalDraft,
    FinancialGoalEventKind,
    FinancialGoalEventRecord,
    FinancialGoalProgressStatus,
    FinancialGoalRecord,
    FinancialGoalReplacement,
    FinancialVisibilityScope,
    Money,
    new_financial_resource_id,
)
from meufinanceiro_persistence.financial_goal_store import FinancialGoalConflictError

from app.services.financial_goals import FinancialGoalService, GoalRequestError

_NOW = datetime(2026, 10, 7, tzinfo=UTC)
_OWNER = uuid4()


def _money(amount: str) -> Money:
    return Money(Decimal(amount), "BRL")


def _record(
    owner: UUID = _OWNER, target_date: date | None = None
) -> FinancialGoalRecord:
    return FinancialGoalRecord(
        id=new_financial_resource_id(),
        residence_id=uuid4(),
        owner_operator_id=owner,
        visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
        title="Viagem",
        description=None,
        target=_money("1000"),
        target_date=target_date,
        version=1,
        created_at=_NOW,
        updated_at=_NOW,
    )


class _Store:
    def __init__(self, record: FinancialGoalRecord) -> None:
        self.record = record
        self.calls: list[str] = []
        self.allocated = _money("250")
        self.account_id = new_financial_resource_id()
        self.created: dict[UUID, FinancialGoalDraft] = {}

    def create_goal(
        self,
        *,
        idempotency_key: UUID,
        draft: FinancialGoalDraft,
        new_goal_guard: Callable[[FinancialGoalDraft], None] | None = None,
        **kwargs: object,
    ) -> FinancialGoalRecord:
        """Mirror the real store: the key decides replay vs. new; only new is guarded."""
        self.calls.append("create")
        previous = self.created.get(idempotency_key)
        if previous is not None:
            if previous != draft:
                raise FinancialGoalConflictError("goal idempotency conflict")
            return self.record
        if new_goal_guard is not None:
            new_goal_guard(draft)
        self.created[idempotency_key] = draft
        return self.record

    def get_goal(self, **kwargs: object) -> FinancialGoalRecord:
        self.calls.append("get")
        return self.record

    def list_goals(
        self, **kwargs: object
    ) -> tuple[tuple[FinancialGoalRecord, Money], ...]:
        self.calls.append("list")
        return ((self.record, self.allocated),)

    def replace_goal(self, **kwargs: object) -> FinancialGoalRecord:
        self.calls.append("replace")
        return self.record

    def allocate(self, **kwargs: object) -> FinancialGoalEventRecord:
        self.calls.append("allocate")
        draft = kwargs["draft"]
        assert isinstance(draft, FinancialGoalAllocationDraft)
        return FinancialGoalEventRecord(
            id=new_financial_resource_id(),
            goal_id=self.record.id,
            account_id=draft.account_id,
            kind=draft.kind,
            amount=draft.amount,
            actor_operator_id=_OWNER,
            created_at=_NOW,
        )

    def read_goal_facts(self, **kwargs: object):
        self.calls.append("facts")
        event = FinancialGoalEventRecord(
            id=new_financial_resource_id(),
            goal_id=self.record.id,
            account_id=self.account_id,
            kind=FinancialGoalEventKind.ALLOCATE,
            amount=self.allocated,
            actor_operator_id=_OWNER,
            created_at=_NOW,
        )
        account = FinancialGoalAccountInput(
            account_id=self.account_id,
            account_status=FinancialAccountStatus.ACTIVE,
            balance=_money("100"),
            allocated_total=self.allocated,
        )
        return self.record, (event,), (account,)


def _scope(operator: UUID = _OWNER) -> dict[str, UUID]:
    return {
        "installation_id": uuid4(),
        "residence_id": uuid4(),
        "operator_id": operator,
    }


def _service(store: _Store, today: date = date(2026, 10, 7)) -> FinancialGoalService:
    return FinancialGoalService(store, clock=lambda: today)


def _draft(target_date: date | None = None) -> FinancialGoalDraft:
    return FinancialGoalDraft(
        title="Viagem",
        description=None,
        visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
        target=_money("1000"),
        target_date=target_date,
    )


def test_the_service_requires_the_store_boundary() -> None:
    with pytest.raises(TypeError):
        FinancialGoalService(object())  # type: ignore[arg-type]


def test_can_edit_is_decided_by_ownership() -> None:
    store = _Store(_record())
    service = _service(store)

    assert service.get_goal(**_scope(), goal_id=store.record.id).can_edit is True
    assert (
        service.get_goal(**_scope(uuid4()), goal_id=store.record.id).can_edit is False
    )
    (item,) = service.list_goals(**_scope(uuid4()))
    assert item.can_edit is False


def test_list_derives_progress_from_the_stored_total() -> None:
    store = _Store(_record())

    (item,) = _service(store).list_goals(**_scope())

    assert item.allocated == _money("250")
    assert item.remaining_target == _money("750")
    assert item.progress_percent == Decimal("25.00")
    assert item.progress_status is FinancialGoalProgressStatus.IN_PROGRESS


def test_summary_is_the_pure_domain_summary() -> None:
    store = _Store(_record())

    view = _service(store).summary(**_scope(), goal_id=store.record.id)

    summary = view.summary
    assert summary.allocated == _money("250")
    assert summary.has_insufficient_backing is True
    assert summary.accounts[0].shortfall == _money("150")
    assert view.can_edit is True


@pytest.mark.parametrize(
    ("target_date", "valid"),
    [
        (None, True),
        (date(2026, 10, 6), True),
        (date(2026, 10, 5), False),
        (date(2126, 12, 31), True),
        (date(2127, 1, 1), False),
    ],
)
def test_create_validates_the_target_date_against_the_clock(
    target_date: date | None, valid: bool
) -> None:
    store = _Store(_record())
    service = _service(store)

    if valid:
        service.create_goal(
            **_scope(), idempotency_key=uuid4(), draft=_draft(target_date)
        )
        assert store.calls == ["create"]
    else:
        with pytest.raises(GoalRequestError):
            service.create_goal(
                **_scope(), idempotency_key=uuid4(), draft=_draft(target_date)
            )
        assert store.created == {}


class _MovingClock:
    def __init__(self, today: date) -> None:
        self.today = today

    def __call__(self) -> date:
        return self.today


def test_replay_after_the_window_moved_returns_the_same_resource() -> None:
    clock = _MovingClock(date(2026, 10, 7))
    store = _Store(_record())
    service = FinancialGoalService(store, clock=clock)
    scope = _scope()
    key = uuid4()
    draft = _draft(date(2026, 10, 7))  # the earliest accepted day today

    first = service.create_goal(**scope, idempotency_key=key, draft=draft)
    clock.today = date(2026, 10, 9)  # the same date is now outside the window
    replay = service.create_goal(**scope, idempotency_key=key, draft=draft)

    assert replay == first
    assert len(store.created) == 1


def test_changed_material_after_the_window_moved_is_still_a_conflict() -> None:
    clock = _MovingClock(date(2026, 10, 7))
    store = _Store(_record())
    service = FinancialGoalService(store, clock=clock)
    scope = _scope()
    key = uuid4()
    service.create_goal(**scope, idempotency_key=key, draft=_draft(date(2026, 10, 7)))
    clock.today = date(2026, 10, 9)

    # Same key, same expired date, different material: conflict, not a date error.
    changed = FinancialGoalDraft(
        title="Outra",
        description=None,
        visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
        target=_money("1000"),
        target_date=date(2026, 10, 7),
    )
    with pytest.raises(FinancialGoalConflictError):
        service.create_goal(**scope, idempotency_key=key, draft=changed)
    assert len(store.created) == 1


def test_a_new_creation_with_an_aged_out_date_is_still_rejected() -> None:
    clock = _MovingClock(date(2026, 10, 7))
    store = _Store(_record())
    service = FinancialGoalService(store, clock=clock)
    scope = _scope()
    draft = _draft(date(2026, 10, 7))
    service.create_goal(**scope, idempotency_key=uuid4(), draft=draft)
    clock.today = date(2026, 10, 9)

    with pytest.raises(GoalRequestError):
        service.create_goal(**scope, idempotency_key=uuid4(), draft=draft)
    assert len(store.created) == 1


def test_replace_only_revalidates_a_changed_target_date() -> None:
    old = date(2020, 1, 1)
    store = _Store(_record(target_date=old))
    service = _service(store)

    def replacement(target_date: date | None) -> FinancialGoalReplacement:
        return FinancialGoalReplacement(
            expected_version=1,
            title="Viagem",
            description=None,
            target=_money("1000"),
            target_date=target_date,
        )

    # Unchanged (even if now in the past) and cleared dates are accepted ...
    service.replace_goal(
        **_scope(), goal_id=store.record.id, replacement=replacement(old)
    )
    service.replace_goal(
        **_scope(), goal_id=store.record.id, replacement=replacement(None)
    )
    # ... a new past date is not.
    with pytest.raises(GoalRequestError):
        service.replace_goal(
            **_scope(),
            goal_id=store.record.id,
            replacement=replacement(date(2020, 1, 2)),
        )
    assert store.calls.count("replace") == 2


def test_allocate_passes_the_draft_through_unchanged() -> None:
    store = _Store(_record())
    account = new_financial_resource_id()

    event = _service(store).allocate(
        **_scope(),
        goal_id=store.record.id,
        idempotency_key=uuid4(),
        draft=FinancialGoalAllocationDraft(
            FinancialGoalEventKind.RELEASE, account, _money("5")
        ),
    )

    assert event.kind is FinancialGoalEventKind.RELEASE
    assert event.account_id == account and event.amount == _money("5")
