"""Pure v1 project contracts; no tests here depend on a database."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from meufinanceiro_finance.accounts import (
    FinancialAccountRecord,
    FinancialAccountStatus,
    FinancialAccountType,
)
from meufinanceiro_finance.access import FinancialVisibilityScope
from meufinanceiro_finance.money import Money
from meufinanceiro_finance.movements import FinancialMovementRole, FinancialResultEffect
from meufinanceiro_finance.movement_records import FinancialMovementRecord
from meufinanceiro_finance.projects import (
    FinancialProjectDraft,
    FinancialProjectExpenseFact,
    FinancialProjectLinkRevisionDraft,
    FinancialProjectLinkRevisionRecord,
    FinancialProjectProgressStatus,
    FinancialProjectRecord,
    is_project_expense_eligible,
    summarize_project,
)

_NOW = datetime(2026, 10, 8, tzinfo=UTC)


def _project(*, scope=FinancialVisibilityScope.HOUSEHOLD, owner=None, residence=None):
    return FinancialProjectRecord(
        id=uuid4(),
        residence_id=residence or uuid4(),
        owner_operator_id=owner or uuid4(),
        visibility_scope=scope,
        title="Reforma",
        description=None,
        planned=Money(Decimal("400"), "BRL"),
        target_date=None,
        version=1,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _account(project, *, scope=None, owner=None, status=FinancialAccountStatus.ACTIVE):
    return FinancialAccountRecord(
        id=uuid4(),
        residence_id=project.residence_id,
        owner_operator_id=owner or project.owner_operator_id,
        visibility_scope=scope or project.visibility_scope,
        account_type=FinancialAccountType.CHECKING,
        custom_type_name=None,
        name="Conta",
        currency="BRL",
        status=status,
        created_at=_NOW,
        updated_at=_NOW,
        archived_at=_NOW if status is FinancialAccountStatus.ARCHIVED else None,
    )


def _movement(account, *, effect=FinancialResultEffect.EXPENSE,
              role=FinancialMovementRole.STANDARD, amount="-130",
              original=None):
    return FinancialMovementRecord(
        id=uuid4(),
        account_id=account.id,
        amount=Money(Decimal(amount), "BRL"),
        result_effect=effect,
        role=role,
        effective_date=date(2026, 10, 8),
        competence_date=date(2026, 10, 8),
        description="Obra" if role is FinancialMovementRole.STANDARD else None,
        reversal_of_id=original.id if original else None,
        reversal_reason="Estorno" if original else None,
        created_by_operator_id=account.owner_operator_id,
        created_at=_NOW,
    )


def test_project_planning_is_strict_and_canonical() -> None:
    p = FinancialProjectDraft(
        title="  Reforma  ", description=None,
        visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
        planned=Money(Decimal("400.000"), "BRL"), target_date=None,
    )
    assert p.title == "Reforma"
    assert p.canonical_material()[4] == "400"
    with pytest.raises(ValueError):
        FinancialProjectDraft(
            title="Errado", description=None,
            visibility_scope=FinancialVisibilityScope.SHARED,
            planned=Money(Decimal("1"), "BRL"), target_date=None,
        )
    with pytest.raises(ValueError):
        FinancialProjectDraft(
            title="Errado", description=None,
            visibility_scope=FinancialVisibilityScope.PERSONAL,
            planned=Money(Decimal("0"), "BRL"), target_date=None,
        )


def test_project_eligibility_limits_scope_owner_and_movement() -> None:
    project = _project()
    account = _account(project)
    expense = _movement(account)
    assert is_project_expense_eligible(
        project=project, account=account, movement=expense, for_new_link=True
    )
    assert not is_project_expense_eligible(
        project=project,
        account=replace(account, visibility_scope=FinancialVisibilityScope.PERSONAL),
        movement=expense,
        for_new_link=True,
    )
    assert not is_project_expense_eligible(
        project=project,
        account=replace(account, owner_operator_id=uuid4()),
        movement=expense,
        for_new_link=True,
    )
    assert not is_project_expense_eligible(
        project=project, account=account,
        movement=_movement(account, effect=FinancialResultEffect.INCOME, amount="130"),
        for_new_link=True,
    )
    archived = _account(project, status=FinancialAccountStatus.ARCHIVED)
    old = _movement(archived)
    assert not is_project_expense_eligible(
        project=project, account=archived, movement=old, for_new_link=True
    )
    assert is_project_expense_eligible(
        project=project, account=archived, movement=old, for_new_link=False
    )


def test_unlink_requires_prior_link_and_revision_chain_is_validated() -> None:
    mid, pid, rid = uuid4(), uuid4(), uuid4()
    with pytest.raises(ValueError):
        FinancialProjectLinkRevisionDraft(mid, None, None)
    draft = FinancialProjectLinkRevisionDraft(mid, pid, None)
    assert draft.canonical_material() == (str(mid), str(pid), None)
    first = FinancialProjectLinkRevisionRecord(
        id=rid, movement_id=mid, project_id=pid,
        supersedes_id=None, revision=1, actor_operator_id=uuid4(), created_at=_NOW,
    )
    unlink = FinancialProjectLinkRevisionRecord(
        id=uuid4(), movement_id=mid, project_id=None,
        supersedes_id=first.id, revision=2,
        actor_operator_id=uuid4(), created_at=_NOW,
    )
    assert unlink.project_id is None
    with pytest.raises(ValueError):
        FinancialProjectLinkRevisionRecord(
            id=uuid4(), movement_id=mid, project_id=None,
            supersedes_id=None, revision=1, actor_operator_id=uuid4(), created_at=_NOW,
        )


def test_reversal_cancels_original_exactly_once_without_other_ledger() -> None:
    project = _project()
    account = _account(project)
    first = _movement(account)
    second = _movement(account, amount="-270")
    reversed_by = _movement(
        account, role=FinancialMovementRole.REVERSAL,
        amount="130", original=first,
    )
    s = summarize_project(
        project, [
            FinancialProjectExpenseFact(project.id, first, reversed_by),
            FinancialProjectExpenseFact(project.id, second),
        ]
    )
    assert s.realized == Money(Decimal("270"), "BRL")
    assert s.remaining == Money(Decimal("130"), "BRL")
    assert s.progress_percent == Decimal("67.50")
    assert s.progress_status is FinancialProjectProgressStatus.UNDER
    with pytest.raises(ValueError):
        summarize_project(project, [
            FinancialProjectExpenseFact(project.id, first),
            FinancialProjectExpenseFact(project.id, first),
        ])


def test_project_summary_over_budget_and_bad_reversal_fail_closed() -> None:
    project = _project()
    account = _account(project)
    expense = _movement(account, amount="-401")
    result = summarize_project(
        project, [FinancialProjectExpenseFact(project.id, expense)]
    )
    assert result.progress_status is FinancialProjectProgressStatus.OVER
    assert result.remaining.amount == 0
    assert result.excess.amount == 1
    with pytest.raises(ValueError):
        FinancialProjectExpenseFact(
            project.id, expense,
            _movement(account, role=FinancialMovementRole.REVERSAL,
                      amount="1", original=expense),
        )
