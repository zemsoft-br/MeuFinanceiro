"""Service-level proofs of the pending inbox with in-memory read boundaries.

Pagination, the scan budget of a rule-status filter and the fixed number of reads
are proven here; PostgreSQL/RLS behaviour is proven in the persistence and API
PostgreSQL suites.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from meufinanceiro_finance import (
    PENDING_PAGE_LIMIT_MAX,
    FinancialAccountStatus,
    FinancialCategorizationMatcher,
    FinancialCategorizationRuleRecord,
    FinancialCategorizationRuleStatus,
    FinancialCategoryRecord,
    FinancialCategoryStatus,
    FinancialMovementRecord,
    FinancialMovementRole,
    FinancialPendingMovementCandidate,
    FinancialPendingMovementCandidatePage,
    FinancialPendingMovementKey,
    FinancialPendingRuleStatus,
    FinancialResultEffect,
    FinancialVisibilityScope,
    Money,
)

from app.services.financial_pending_movements import (
    MAX_SCAN_BATCHES,
    SCAN_BATCH_SIZE,
    FinancialPendingMovementService,
    PendingMovementsRequestError,
)

_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
_INSTALLATION, _RESIDENCE, _OPERATOR = uuid4(), uuid4(), uuid4()
_ACCOUNT = uuid4()
Status = FinancialPendingRuleStatus


def _candidate(
    description: str, *, day: int, account_id: UUID = _ACCOUNT
) -> FinancialPendingMovementCandidate:
    when = date(2026, 1, 1) + timedelta(days=day)
    return FinancialPendingMovementCandidate(
        movement=FinancialMovementRecord(
            id=uuid4(),
            account_id=account_id,
            amount=Money(Decimal("-10.00"), "BRL"),
            result_effect=FinancialResultEffect.EXPENSE,
            role=FinancialMovementRole.STANDARD,
            effective_date=when,
            competence_date=when,
            description=description,
            reversal_of_id=None,
            reversal_reason=None,
            created_by_operator_id=_OPERATOR,
            created_at=_NOW,
        ),
        account_visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
        account_owner_operator_id=_OPERATOR,
        account_status=FinancialAccountStatus.ACTIVE,
    )


def _rule(pattern: str, *, priority: int = 5) -> FinancialCategorizationRuleRecord:
    return FinancialCategorizationRuleRecord(
        id=uuid4(),
        residence_id=_RESIDENCE,
        created_by_operator_id=_OPERATOR,
        account_id=None,
        result_effect=None,
        description_matcher=FinancialCategorizationMatcher.CONTAINS,
        description_pattern=pattern,
        target_category_id=uuid4(),
        priority=priority,
        status=FinancialCategorizationRuleStatus.ACTIVE,
        created_at=_NOW,
        disabled_at=None,
        disabled_by_operator_id=None,
    )


def _category(category_id: UUID) -> FinancialCategoryRecord:
    return FinancialCategoryRecord(
        id=category_id,
        residence_id=_RESIDENCE,
        owner_operator_id=_OPERATOR,
        visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
        parent_id=None,
        name="Categoria",
        status=FinancialCategoryStatus.ACTIVE,
        created_at=_NOW,
        updated_at=_NOW,
        disabled_at=None,
    )


@dataclass
class Fakes:
    candidates: list[FinancialPendingMovementCandidate]
    rules: list[FinancialCategorizationRuleRecord] = field(default_factory=list)
    page_reads: list[dict[str, object]] = field(default_factory=list)
    rule_reads: int = 0
    category_reads: int = 0
    writes: int = 0

    def __post_init__(self) -> None:
        self.candidates.sort(
            key=lambda c: (c.movement.effective_date, str(c.movement.id)), reverse=True
        )

    # pending boundary
    def list_pending_candidates(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        limit: int,
        after: FinancialPendingMovementKey | None = None,
        account_id: UUID | None = None,
        result_effect: FinancialResultEffect | None = None,
    ) -> FinancialPendingMovementCandidatePage:
        self.page_reads.append({"limit": limit, "after": after})
        assert 1 <= limit <= PENDING_PAGE_LIMIT_MAX
        rows = [
            c
            for c in self.candidates
            if (after is None or _before(c, after))
            and (account_id is None or c.movement.account_id == account_id)
            and (result_effect is None or c.movement.result_effect is result_effect)
        ]
        return FinancialPendingMovementCandidatePage(
            tuple(rows[:limit]), has_more=len(rows) > limit
        )

    # rule boundary
    def list_rules(
        self, **_scope: UUID
    ) -> tuple[FinancialCategorizationRuleRecord, ...]:
        self.rule_reads += 1
        return tuple(self.rules)

    # category boundary
    def list_categories(self, **_scope: UUID) -> tuple[FinancialCategoryRecord, ...]:
        self.category_reads += 1
        return tuple(_category(rule.target_category_id) for rule in self.rules)

    def service(self) -> FinancialPendingMovementService:
        return FinancialPendingMovementService(self, self, self)  # type: ignore[arg-type]

    def list(self, **kwargs: object):  # type: ignore[no-untyped-def]
        return self.service().list_pending(
            installation_id=_INSTALLATION,
            residence_id=_RESIDENCE,
            operator_id=_OPERATOR,
            **kwargs,  # type: ignore[arg-type]
        )


def _before(
    candidate: FinancialPendingMovementCandidate, key: FinancialPendingMovementKey
) -> bool:
    return (candidate.movement.effective_date, str(candidate.movement.id)) < (
        key.effective_date,
        str(key.movement_id),
    )


def _walk(fakes: Fakes, **kwargs: object) -> tuple[list[UUID], int]:
    seen: list[UUID] = []
    cursor: str | None = None
    pages = 0
    while True:
        page = fakes.list(cursor=cursor, **kwargs)
        pages += 1
        seen.extend(item.candidate.movement.id for item in page.items)
        if page.next_cursor is None:
            return seen, pages
        cursor = page.next_cursor
        assert pages < 500


# --- no filter: one page read ----------------------------------------------


def test_unfiltered_page_costs_one_page_read_one_rule_read_one_category_read() -> None:
    rule = _rule("padaria")
    fakes = Fakes([_candidate("padaria", day=i) for i in range(30)], rules=[rule])
    page = fakes.list(limit=10)
    assert len(page.items) == 10 and page.next_cursor is not None
    assert (len(fakes.page_reads), fakes.rule_reads, fakes.category_reads) == (1, 1, 1)
    assert fakes.page_reads[0]["limit"] == 10
    assert all(item.rule_status is Status.MATCHED for item in page.items)
    assert fakes.writes == 0


def test_last_page_has_no_cursor_and_walk_never_repeats() -> None:
    fakes = Fakes([_candidate(f"item {i}", day=i % 7) for i in range(23)])
    seen, pages = _walk(fakes, limit=5)
    assert pages == 5
    assert len(seen) == len(set(seen)) == 23
    assert seen == [c.movement.id for c in fakes.candidates]


def test_cost_does_not_grow_with_inbox_size() -> None:
    small = Fakes([_candidate("x", day=i) for i in range(3)], rules=[_rule("x")])
    large = Fakes([_candidate("x", day=i) for i in range(900)], rules=[_rule("x")])
    small.list(limit=50)
    large.list(limit=50)
    for fakes in (small, large):
        assert (len(fakes.page_reads), fakes.rule_reads, fakes.category_reads) == (
            1,
            1,
            1,
        )


def test_default_and_boundary_limits_and_bad_requests() -> None:
    fakes = Fakes([_candidate("x", day=i) for i in range(120)])
    assert len(fakes.list().items) == 50
    assert len(fakes.list(limit=PENDING_PAGE_LIMIT_MAX).items) == 100
    for bad in (0, -1, PENDING_PAGE_LIMIT_MAX + 1, True, "5", None):
        with pytest.raises(PendingMovementsRequestError):
            fakes.list(limit=bad)
    with pytest.raises(PendingMovementsRequestError):
        fakes.list(cursor="not-a-cursor")
    with pytest.raises(PendingMovementsRequestError):
        fakes.list(result_effect=FinancialResultEffect.NEUTRAL)
    with pytest.raises(PendingMovementsRequestError):
        fakes.list(account_id=uuid4().hex)  # type: ignore[arg-type]


def test_cursor_cannot_be_reused_under_other_filters() -> None:
    fakes = Fakes([_candidate("x", day=i) for i in range(10)])
    cursor = fakes.list(limit=3).next_cursor
    assert cursor is not None
    for other in (
        {"rule_status": Status.MATCHED},
        {"account_id": _ACCOUNT},
        {"result_effect": FinancialResultEffect.EXPENSE},
    ):
        with pytest.raises(PendingMovementsRequestError):
            fakes.list(limit=3, cursor=cursor, **other)
    assert fakes.list(limit=3, cursor=cursor).items


# --- rule status filter: bounded scan --------------------------------------


def _mixed(n: int) -> Fakes:
    """Every item matches one rule except each 10th, which is NO_MATCH."""
    rule = _rule("padaria")
    return Fakes(
        [_candidate("cinema" if i % 10 == 0 else "padaria", day=i) for i in range(n)],
        rules=[rule],
    )


def test_status_filter_fills_the_page_and_resumes_exactly_after_the_last_item() -> None:
    fakes = _mixed(60)
    page = fakes.list(limit=5, rule_status=Status.NO_MATCH)
    assert len(page.items) == 5
    assert all(item.rule_status is Status.NO_MATCH for item in page.items)
    assert page.next_cursor is not None
    assert len(fakes.page_reads) == 1  # one 100-candidate batch was enough

    seen, _ = _walk(fakes, limit=5, rule_status=Status.NO_MATCH)
    expected = [
        c.movement.id for c in fakes.candidates if c.movement.description == "cinema"
    ]
    assert seen == expected  # nothing skipped, nothing repeated


def test_status_filter_matches_unfiltered_partition() -> None:
    fakes = _mixed(137)
    everything = fakes.list(limit=100)
    by_status = {
        status: _walk(fakes, limit=7, rule_status=status)[0] for status in Status
    }
    assert by_status[Status.AMBIGUOUS] == []
    union = {*by_status[Status.MATCHED], *by_status[Status.NO_MATCH]}
    assert len(union) == 137
    assert {i.candidate.movement.id for i in everything.items} <= union


def test_status_filter_scan_budget_is_fixed_and_returns_a_cursor() -> None:
    # Nothing matches the filter in the first MAX_SCAN_BATCHES * SCAN_BATCH_SIZE
    # candidates: the page is empty but the inbox is not exhausted.
    total = MAX_SCAN_BATCHES * SCAN_BATCH_SIZE + 40
    rule = _rule("padaria")
    fakes = Fakes(
        [
            _candidate("cinema" if i >= total - 40 else "padaria", day=total - i)
            for i in range(total)
        ],
        rules=[rule],
    )
    page = fakes.list(limit=10, rule_status=Status.NO_MATCH)
    # Newest first: the first 500 are padaria (MATCHED); NO_MATCH ones come last.
    assert page.items == ()
    assert page.next_cursor is not None
    assert len(fakes.page_reads) == MAX_SCAN_BATCHES
    assert (fakes.rule_reads, fakes.category_reads) == (1, 1)

    # The client follows the cursor and the remaining NO_MATCH items arrive.
    seen, _ = _walk(fakes, limit=10, rule_status=Status.NO_MATCH)
    assert len(seen) == 40


def test_status_filter_with_no_candidates_has_no_cursor() -> None:
    fakes = Fakes([])
    page = fakes.list(limit=5, rule_status=Status.MATCHED)
    assert page.items == () and page.next_cursor is None
    assert len(fakes.page_reads) == 1


def test_status_filter_exact_fit_on_the_final_candidate_has_no_cursor() -> None:
    fakes = Fakes([_candidate("cinema", day=i) for i in range(4)])
    page = fakes.list(limit=4, rule_status=Status.NO_MATCH)
    assert len(page.items) == 4 and page.next_cursor is None


def test_ambiguous_items_never_carry_a_rule() -> None:
    fakes = Fakes(
        [_candidate("mercado", day=1)], rules=[_rule("mercado"), _rule("mercado")]
    )
    (item,) = fakes.list().items
    assert item.rule_status is Status.AMBIGUOUS and item.rule is None


def test_service_requires_the_three_read_boundaries() -> None:
    with pytest.raises(TypeError):
        FinancialPendingMovementService(object(), object(), object())  # type: ignore[arg-type]
