from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from meufinanceiro_finance import (
    GOAL_ACCOUNTS_MAX,
    GOAL_EVENTS_MAX,
    GOAL_TITLE_MAX_LENGTH,
    FinancialAccountRecord,
    FinancialAccountStatus,
    FinancialAccountType,
    FinancialGoalAccountInput,
    FinancialGoalAllocationDraft,
    FinancialGoalAllocationError,
    FinancialGoalBackingStatus,
    FinancialGoalDraft,
    FinancialGoalEventKind,
    FinancialGoalEventRecord,
    FinancialGoalInsufficientAllocationError,
    FinancialGoalInsufficientAvailabilityError,
    FinancialGoalProgressStatus,
    FinancialGoalRecord,
    FinancialGoalReplacement,
    FinancialVisibilityScope,
    Money,
    can_edit_goal,
    goal_account_availability,
    goal_progress_percent,
    goal_target_date_bounds,
    is_goal_account_eligible,
    net_allocated_by_account,
    new_financial_resource_id,
    require_allocation_within_availability,
    require_release_within_allocated,
    summarize_goal,
    validate_goal_target_date,
)

_NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
_OWNER = uuid4()
_RESIDENCE = uuid4()
PERSONAL = FinancialVisibilityScope.PERSONAL
HOUSEHOLD = FinancialVisibilityScope.HOUSEHOLD
SHARED = FinancialVisibilityScope.SHARED


def _money(amount: str, currency: str = "BRL") -> Money:
    return Money(Decimal(amount), currency)


def _draft(**overrides: object) -> FinancialGoalDraft:
    values: dict[str, object] = {
        "title": "Reserva de emergência",
        "description": None,
        "visibility_scope": PERSONAL,
        "target": _money("10000"),
        "target_date": None,
    }
    values.update(overrides)
    return FinancialGoalDraft(**values)  # type: ignore[arg-type]


def _goal(**overrides: object) -> FinancialGoalRecord:
    values: dict[str, object] = {
        "id": new_financial_resource_id(),
        "residence_id": _RESIDENCE,
        "owner_operator_id": _OWNER,
        "visibility_scope": PERSONAL,
        "title": "Viagem",
        "description": None,
        "target": _money("1000"),
        "target_date": None,
        "version": 1,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    values.update(overrides)
    return FinancialGoalRecord(**values)  # type: ignore[arg-type]


def _account(**overrides: object) -> FinancialAccountRecord:
    values: dict[str, object] = {
        "id": new_financial_resource_id(),
        "residence_id": _RESIDENCE,
        "owner_operator_id": _OWNER,
        "visibility_scope": PERSONAL,
        "account_type": FinancialAccountType.CHECKING,
        "custom_type_name": None,
        "name": "Conta",
        "currency": "BRL",
        "status": FinancialAccountStatus.ACTIVE,
        "created_at": _NOW,
        "updated_at": _NOW,
        "archived_at": None,
    }
    values.update(overrides)
    return FinancialAccountRecord(**values)  # type: ignore[arg-type]


def _event(
    goal: FinancialGoalRecord,
    account_id,
    kind: FinancialGoalEventKind,
    amount: str,
) -> FinancialGoalEventRecord:
    return FinancialGoalEventRecord(
        id=new_financial_resource_id(),
        goal_id=goal.id,
        account_id=account_id,
        kind=kind,
        amount=_money(amount),
        actor_operator_id=_OWNER,
        created_at=_NOW,
    )


A = FinancialGoalEventKind.ALLOCATE
R = FinancialGoalEventKind.RELEASE


def test_draft_normalizes_text_and_exposes_currency() -> None:
    draft = _draft(title="  Casa  ", description="   ")

    assert draft.title == "Casa"
    assert draft.description is None
    assert draft.currency == "BRL"


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": ""},
        {"title": "x" * (GOAL_TITLE_MAX_LENGTH + 1)},
        {"title": "line\nbreak"},
        {"description": "x" * 281},
        {"description": "tab\there"},
        {"visibility_scope": SHARED},
        {"target": _money("0")},
        {"target": _money("-1")},
        {"target_date": datetime(2027, 1, 1, tzinfo=UTC)},
    ],
)
def test_draft_rejects_invalid_material(overrides: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        _draft(**overrides)


def test_draft_rejects_non_money_target_and_float() -> None:
    with pytest.raises(TypeError):
        _draft(target=1000.0)


def test_canonical_material_is_stable_and_currency_aware() -> None:
    first = _draft(target_date=date(2027, 1, 1)).canonical_material()

    assert first == _draft(target_date=date(2027, 1, 1)).canonical_material()
    assert first != _draft(target=_money("10000", "USD")).canonical_material()
    assert first != _draft(target_date=None).canonical_material()
    assert first != _draft(visibility_scope=HOUSEHOLD).canonical_material()


def test_replacement_requires_a_positive_integer_version() -> None:
    values = {
        "title": "x",
        "description": None,
        "target": _money("1"),
        "target_date": None,
    }
    for bad in (0, -1, True, "1", 1.0):
        with pytest.raises((TypeError, ValueError)):
            FinancialGoalReplacement(expected_version=bad, **values)  # type: ignore[arg-type]
    assert FinancialGoalReplacement(expected_version=3, **values).expected_version == 3  # type: ignore[arg-type]


def test_record_rejects_inconsistent_state() -> None:
    with pytest.raises(ValueError):
        _goal(updated_at=datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(ValueError):
        _goal(created_at=datetime(2026, 10, 7))
    with pytest.raises(ValueError):
        _goal(version=0)
    with pytest.raises(ValueError):
        _goal(id=UUID(int=1))


def test_only_the_owner_can_edit() -> None:
    goal = _goal(visibility_scope=HOUSEHOLD)

    assert can_edit_goal(goal=goal, operator_id=_OWNER) is True
    assert can_edit_goal(goal=goal, operator_id=uuid4()) is False


def test_target_date_bounds_are_explicit() -> None:
    today = date(2026, 10, 7)
    earliest, latest = goal_target_date_bounds(today)

    assert earliest == date(2026, 10, 6)
    assert latest == date(2126, 12, 31)
    assert validate_goal_target_date(None, today=today) is None
    assert validate_goal_target_date(date(2026, 10, 6), today=today) == date(
        2026, 10, 6
    )
    assert validate_goal_target_date(date(2126, 12, 31), today=today) == date(
        2126, 12, 31
    )
    for outside in (date(2026, 10, 5), date(2127, 1, 1)):
        with pytest.raises(ValueError):
            validate_goal_target_date(outside, today=today)
    with pytest.raises(TypeError):
        validate_goal_target_date("2027-01-01", today=today)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("goal_scope", "account_scope", "same_owner", "currency", "status", "new", "ok"),
    [
        (PERSONAL, PERSONAL, True, "BRL", "ACTIVE", True, True),
        (HOUSEHOLD, HOUSEHOLD, True, "BRL", "ACTIVE", True, True),
        (PERSONAL, HOUSEHOLD, True, "BRL", "ACTIVE", True, False),
        (HOUSEHOLD, PERSONAL, True, "BRL", "ACTIVE", True, False),
        (PERSONAL, SHARED, True, "BRL", "ACTIVE", True, False),
        (HOUSEHOLD, SHARED, True, "BRL", "ACTIVE", True, False),
        (PERSONAL, PERSONAL, False, "BRL", "ACTIVE", True, False),
        (HOUSEHOLD, HOUSEHOLD, False, "BRL", "ACTIVE", True, False),
        (PERSONAL, PERSONAL, True, "USD", "ACTIVE", True, False),
        (PERSONAL, PERSONAL, True, "BRL", "ARCHIVED", True, False),
        (PERSONAL, PERSONAL, True, "BRL", "ARCHIVED", False, True),
    ],
)
def test_account_eligibility_matrix(
    goal_scope, account_scope, same_owner, currency, status, new, ok
) -> None:
    archived = status == "ARCHIVED"
    account = _account(
        visibility_scope=account_scope,
        owner_operator_id=_OWNER if same_owner else uuid4(),
        currency=currency,
        status=FinancialAccountStatus(status),
        archived_at=_NOW if archived else None,
    )

    assert (
        is_goal_account_eligible(
            goal_visibility_scope=goal_scope,
            goal_owner_operator_id=_OWNER,
            goal_currency="BRL",
            account=account,
            for_new_allocation=new,
        )
        is ok
    )


def test_allocation_draft_signs_and_validates() -> None:
    account_id = new_financial_resource_id()

    allocate = FinancialGoalAllocationDraft(A, account_id, _money("10.5"))
    release = FinancialGoalAllocationDraft(R, account_id, _money("10.5"))

    assert allocate.signed_amount == Decimal("10.5")
    assert release.signed_amount == Decimal("-10.5")
    assert allocate.canonical_material() != release.canonical_material()
    for bad in ("0", "-1"):
        with pytest.raises(ValueError):
            FinancialGoalAllocationDraft(A, account_id, _money(bad))
    with pytest.raises(TypeError):
        FinancialGoalAllocationDraft("ALLOCATE", account_id, _money("1"))  # type: ignore[arg-type]


def test_net_allocated_by_account_sums_signed_events() -> None:
    goal = _goal()
    first, second = new_financial_resource_id(), new_financial_resource_id()
    events = [
        _event(goal, first, A, "100"),
        _event(goal, second, A, "50"),
        _event(goal, first, R, "30"),
    ]

    assert net_allocated_by_account(events) == {
        first: Decimal("70"),
        second: Decimal("50"),
    }
    with pytest.raises(FinancialGoalAllocationError):
        net_allocated_by_account([_event(goal, first, R, "1")])


def test_availability_is_balance_minus_every_goal_and_never_floored() -> None:
    assert goal_account_availability(
        balance=_money("100"), allocated_total=_money("40")
    ) == _money("60")
    assert goal_account_availability(
        balance=_money("30"), allocated_total=_money("40")
    ) == _money("-10")


def test_allocation_must_fit_in_availability() -> None:
    require_allocation_within_availability(
        balance=_money("100"), allocated_total=_money("40"), amount=_money("60")
    )
    with pytest.raises(FinancialGoalInsufficientAvailabilityError):
        require_allocation_within_availability(
            balance=_money("100"),
            allocated_total=_money("40"),
            amount=_money("60.00000001"),
        )
    # Already lacking backing: nothing new may be allocated, not even a cent.
    with pytest.raises(FinancialGoalInsufficientAvailabilityError):
        require_allocation_within_availability(
            balance=_money("30"),
            allocated_total=_money("40"),
            amount=_money("0.00000001"),
        )
    # Allocation never uses another currency's balance.
    with pytest.raises(ValueError):
        require_allocation_within_availability(
            balance=_money("100"),
            allocated_total=_money("0", "USD"),
            amount=_money("1"),
        )


def test_release_must_fit_in_what_the_goal_holds() -> None:
    require_release_within_allocated(allocated=_money("10"), amount=_money("10"))
    with pytest.raises(FinancialGoalInsufficientAllocationError):
        require_release_within_allocated(allocated=_money("10"), amount=_money("10.01"))


@pytest.mark.parametrize(
    ("target", "allocated", "expected"),
    [
        ("1000", "0", "0.00"),
        ("1000", "333.33333333", "33.33"),
        ("3", "1", "33.33"),
        ("3", "2", "66.67"),
        ("1000", "1000", "100.00"),
        ("1000", "1500", "150.00"),
        ("0.00000003", "0.00000001", "33.33"),
        ("200", "0.005", "0.00"),
        ("200", "0.01", "0.01"),
    ],
)
def test_progress_percent_is_half_up_at_two_places(
    target: str, allocated: str, expected: str
) -> None:
    assert goal_progress_percent(Decimal(target), Decimal(allocated)) == Decimal(
        expected
    )


def test_progress_percent_rejects_a_non_positive_target() -> None:
    with pytest.raises(ValueError):
        goal_progress_percent(Decimal(0), Decimal(1))


def _inputs(goal, account_id, balance="500", total="500"):
    return FinancialGoalAccountInput(
        account_id=account_id,
        account_status=FinancialAccountStatus.ACTIVE,
        balance=_money(balance),
        allocated_total=_money(total),
    )


def test_summary_of_a_goal_without_events_is_not_started() -> None:
    summary = summarize_goal(_goal(), [], [])

    assert summary.allocated == _money("0")
    assert summary.remaining_target == _money("1000")
    assert summary.surplus == _money("0")
    assert summary.progress_percent == Decimal("0.00")
    assert summary.progress_status is FinancialGoalProgressStatus.NOT_STARTED
    assert summary.has_insufficient_backing is False
    assert summary.accounts == ()


def test_summary_n_accounts_and_progress() -> None:
    goal = _goal(target=_money("1000"))
    first, second = new_financial_resource_id(), new_financial_resource_id()
    events = [
        _event(goal, first, A, "300"),
        _event(goal, second, A, "200"),
        _event(goal, first, R, "50"),
    ]

    summary = summarize_goal(
        goal,
        events,
        [_inputs(goal, first, "900", "250"), _inputs(goal, second, "200", "200")],
    )

    assert summary.allocated == _money("450")
    assert summary.remaining_target == _money("550")
    assert summary.progress_percent == Decimal("45.00")
    assert summary.progress_status is FinancialGoalProgressStatus.IN_PROGRESS
    assert {account.account_id: account.allocated for account in summary.accounts} == {
        first: _money("250"),
        second: _money("200"),
    }
    assert summary.has_insufficient_backing is False
    assert all(
        account.backing_status is FinancialGoalBackingStatus.COVERED
        for account in summary.accounts
    )


def test_summary_flags_insufficient_backing_without_rewriting_anything() -> None:
    goal = _goal(target=_money("1000"))
    account_id = new_financial_resource_id()
    events = [_event(goal, account_id, A, "400")]

    summary = summarize_goal(
        goal, events, [_inputs(goal, account_id, balance="150", total="400")]
    )

    (account,) = summary.accounts
    assert account.backing_status is FinancialGoalBackingStatus.INSUFFICIENT
    assert account.shortfall == _money("250")
    assert summary.has_insufficient_backing is True
    # The goal still reports exactly what was explicitly allocated.
    assert summary.allocated == _money("400")
    assert summary.events == tuple(events)


def test_summary_backing_is_account_wide_not_goal_local() -> None:
    goal = _goal(target=_money("1000"))
    account_id = new_financial_resource_id()
    events = [_event(goal, account_id, A, "100")]

    # Another goal also holds 300 on the account: 400 allocated against 350 balance.
    summary = summarize_goal(
        goal, events, [_inputs(goal, account_id, balance="350", total="400")]
    )

    assert summary.accounts[0].backing_status is FinancialGoalBackingStatus.INSUFFICIENT
    assert summary.accounts[0].shortfall == _money("50")


def test_summary_target_reached_and_exceeded_and_lowered_target() -> None:
    account_id = new_financial_resource_id()
    goal = _goal(target=_money("100"))
    reached = summarize_goal(
        goal,
        [_event(goal, account_id, A, "100")],
        [_inputs(goal, account_id, "100", "100")],
    )
    assert reached.progress_status is FinancialGoalProgressStatus.REACHED
    assert reached.remaining_target == _money("0")

    lowered = _goal(id=goal.id, target=_money("60"))
    exceeded = summarize_goal(
        lowered,
        [_event(lowered, account_id, A, "100")],
        [_inputs(lowered, account_id, "100", "100")],
    )
    assert exceeded.progress_status is FinancialGoalProgressStatus.EXCEEDED
    assert exceeded.remaining_target == _money("0")
    assert exceeded.surplus == _money("40")
    assert exceeded.progress_percent == Decimal("166.67")


def test_summary_rejects_inconsistent_inputs() -> None:
    goal = _goal()
    account_id = new_financial_resource_id()
    other_goal = _goal()
    with pytest.raises(FinancialGoalAllocationError):
        summarize_goal(goal, [_event(other_goal, account_id, A, "1")], [])
    with pytest.raises(FinancialGoalAllocationError):
        summarize_goal(goal, [_event(goal, account_id, A, "1")], [])
    with pytest.raises(FinancialGoalAllocationError):
        summarize_goal(
            goal,
            [],
            [_inputs(goal, account_id)],
        )
    foreign = FinancialGoalEventRecord(
        id=new_financial_resource_id(),
        goal_id=goal.id,
        account_id=account_id,
        kind=A,
        amount=_money("1", "USD"),
        actor_operator_id=_OWNER,
        created_at=_NOW,
    )
    with pytest.raises(FinancialGoalAllocationError):
        summarize_goal(goal, [foreign], [_inputs(goal, account_id)])


def test_summary_enforces_explicit_bounds_without_truncating() -> None:
    goal = _goal()
    account_id = new_financial_resource_id()
    events = [_event(goal, account_id, A, "1") for _ in range(GOAL_EVENTS_MAX + 1)]
    with pytest.raises(FinancialGoalAllocationError):
        summarize_goal(goal, events, [_inputs(goal, account_id, "9999", "9999")])

    many = [new_financial_resource_id() for _ in range(GOAL_ACCOUNTS_MAX + 1)]
    with pytest.raises(FinancialGoalAllocationError):
        summarize_goal(
            goal,
            [_event(goal, account, A, "1") for account in many],
            [_inputs(goal, account, "10", "1") for account in many],
        )


def test_summary_with_zero_net_account_is_kept_for_history() -> None:
    goal = _goal()
    account_id = new_financial_resource_id()
    events = [_event(goal, account_id, A, "10"), _event(goal, account_id, R, "10")]

    summary = summarize_goal(goal, events, [_inputs(goal, account_id, "0", "0")])

    assert summary.accounts[0].allocated == _money("0")
    assert summary.allocated == _money("0")
    assert summary.progress_status is FinancialGoalProgressStatus.NOT_STARTED


def test_reprs_do_not_leak_values() -> None:
    goal = _goal(title="Segredo da família")
    rendered = " ".join(
        repr(item)
        for item in (
            goal,
            _draft(title="Segredo da família"),
            FinancialGoalAllocationDraft(
                A, new_financial_resource_id(), _money("123.45")
            ),
        )
    )

    assert "Segredo" not in rendered
    assert "123.45" not in rendered
