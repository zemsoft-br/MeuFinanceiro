"""Authenticated, read-only cash flow route (ADR-0031).

``GET /finance/cash-flow`` is the only operation: there is deliberately no
``POST``, ``PUT``, ``PATCH`` or ``DELETE``. The response is the serialization of
the pure domain projection read from one consistent snapshot; nothing is
generated, written or computed here. Money is always decimal text.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from datetime import date as _Date
from typing import Annotated, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from meufinanceiro_finance import (
    CASH_FLOW_ACCOUNTS_MAX,
    FinancialCashFlowAccountSummary,
    FinancialCashFlowDay,
    FinancialCashFlowEvent,
    FinancialCashFlowGroup,
    FinancialCashFlowIssue,
    FinancialCashFlowProjection,
    FinancialCashFlowRisk,
    FinancialCashFlowTotals,
    Money,
    validate_financial_resource_id,
)
from meufinanceiro_persistence.financial_cash_flow_store import (
    FinancialCashFlowAccessError,
    FinancialCashFlowAccountNotFoundError,
    FinancialCashFlowLimitExceededError,
    FinancialCashFlowPersistenceError,
)
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import AuthenticatedOperatorRequest, require_primary_residence
from app.services.financial_cash_flow import (
    CashFlowRequestError,
    FinancialCashFlowService,
)

router = APIRouter(prefix="/finance", tags=["finance"])

_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
_SINGLE_PARAMETERS = frozenset(("from", "through", "currency"))
_PARAMETERS = _SINGLE_PARAMETERS | {"accountId"}


class CashFlowMoneyResponse(BaseModel):
    amount: str
    currency: str


class CashFlowRiskResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    minimum_balance: CashFlowMoneyResponse = Field(serialization_alias="minimumBalance")
    minimum_balance_date: date = Field(serialization_alias="minimumBalanceDate")
    first_negative_date: date | None = Field(serialization_alias="firstNegativeDate")
    negative_days: int = Field(serialization_alias="negativeDays")


class CashFlowIssueResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code: str
    severity: str
    count: int
    account_ids: tuple[UUID, ...] = Field(serialization_alias="accountIds")


class CashFlowTotalsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    realized_income: CashFlowMoneyResponse = Field(serialization_alias="realizedIncome")
    realized_expense: CashFlowMoneyResponse = Field(
        serialization_alias="realizedExpense"
    )
    neutral_in: CashFlowMoneyResponse = Field(serialization_alias="neutralIn")
    neutral_out: CashFlowMoneyResponse = Field(serialization_alias="neutralOut")
    realized_net: CashFlowMoneyResponse = Field(serialization_alias="realizedNet")
    expected_income: CashFlowMoneyResponse = Field(serialization_alias="expectedIncome")
    expected_expense: CashFlowMoneyResponse = Field(
        serialization_alias="expectedExpense"
    )
    expected_net: CashFlowMoneyResponse = Field(serialization_alias="expectedNet")
    overdue_count: int = Field(serialization_alias="overdueCount")
    overdue_net: CashFlowMoneyResponse = Field(serialization_alias="overdueNet")
    recurrence_realized_count: int = Field(
        serialization_alias="recurrenceRealizedCount"
    )
    recurrence_realized_expected: CashFlowMoneyResponse = Field(
        serialization_alias="recurrenceRealizedExpected"
    )
    recurrence_realized_actual: CashFlowMoneyResponse = Field(
        serialization_alias="recurrenceRealizedActual"
    )
    realized_count: int = Field(serialization_alias="realizedCount")
    expected_count: int = Field(serialization_alias="expectedCount")


class CashFlowAccountResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    account_id: UUID = Field(serialization_alias="accountId")
    name: str
    account_type: str = Field(serialization_alias="accountType")
    visibility_scope: str = Field(serialization_alias="visibilityScope")
    status: str
    has_opening_balance: bool = Field(serialization_alias="hasOpeningBalance")
    opening_balance_date: date | None = Field(serialization_alias="openingBalanceDate")
    starting_balance: CashFlowMoneyResponse = Field(
        serialization_alias="startingBalance"
    )
    balance_at_reference: CashFlowMoneyResponse = Field(
        serialization_alias="balanceAtReference"
    )
    realized_net: CashFlowMoneyResponse = Field(serialization_alias="realizedNet")
    expected_net: CashFlowMoneyResponse = Field(serialization_alias="expectedNet")
    closing_balance: CashFlowMoneyResponse = Field(serialization_alias="closingBalance")
    risk: CashFlowRiskResponse


class CashFlowDayResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    date: date
    opening: CashFlowMoneyResponse
    realized_income: CashFlowMoneyResponse = Field(serialization_alias="realizedIncome")
    realized_expense: CashFlowMoneyResponse = Field(
        serialization_alias="realizedExpense"
    )
    expected_income: CashFlowMoneyResponse = Field(serialization_alias="expectedIncome")
    expected_expense: CashFlowMoneyResponse = Field(
        serialization_alias="expectedExpense"
    )
    neutral_net: CashFlowMoneyResponse = Field(serialization_alias="neutralNet")
    closing: CashFlowMoneyResponse
    projected: bool
    negative: bool


class CashFlowEventResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    date: _Date
    kind: str
    account_id: UUID = Field(serialization_alias="accountId")
    amount: CashFlowMoneyResponse
    result_effect: str = Field(serialization_alias="resultEffect")
    description: str | None
    movement_id: UUID | None = Field(serialization_alias="movementId")
    movement_role: str | None = Field(serialization_alias="movementRole")
    reversal_of_id: UUID | None = Field(serialization_alias="reversalOfId")
    transfer_id: UUID | None = Field(serialization_alias="transferId")
    occurrence_id: UUID | None = Field(serialization_alias="occurrenceId")
    recurrence_id: UUID | None = Field(serialization_alias="recurrenceId")
    rule_version: int | None = Field(serialization_alias="ruleVersion")
    period_start: _Date | None = Field(serialization_alias="periodStart")
    scheduled_date: _Date | None = Field(serialization_alias="scheduledDate")
    overdue: bool
    expected_amount: CashFlowMoneyResponse | None = Field(
        serialization_alias="expectedAmount"
    )
    balance_after: CashFlowMoneyResponse = Field(serialization_alias="balanceAfter")
    account_balance_after: CashFlowMoneyResponse = Field(
        serialization_alias="accountBalanceAfter"
    )


class CashFlowGroupResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    currency: str
    projection_status: str = Field(serialization_alias="projectionStatus")
    issues: tuple[CashFlowIssueResponse, ...]
    starting_balance: CashFlowMoneyResponse = Field(
        serialization_alias="startingBalance"
    )
    balance_at_reference: CashFlowMoneyResponse = Field(
        serialization_alias="balanceAtReference"
    )
    closing_balance: CashFlowMoneyResponse = Field(serialization_alias="closingBalance")
    totals: CashFlowTotalsResponse
    risk: CashFlowRiskResponse
    accounts: tuple[CashFlowAccountResponse, ...]
    days: tuple[CashFlowDayResponse, ...]
    events: tuple[CashFlowEventResponse, ...]


class CashFlowResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    reference_date: date = Field(serialization_alias="referenceDate")
    from_date: date = Field(serialization_alias="from")
    through_date: date = Field(serialization_alias="through")
    days: int
    calculated_at: datetime = Field(serialization_alias="calculatedAt")
    excluded_sources: tuple[str, ...] = Field(serialization_alias="excludedSources")
    groups: tuple[CashFlowGroupResponse, ...]


def _service(request: Request) -> FinancialCashFlowService:
    service = getattr(request.app.state, "financial_cash_flow", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="financial service is unavailable",
        )
    return cast(FinancialCashFlowService, service)


def _context(authenticated: AuthenticatedOperatorRequest) -> tuple[UUID, UUID, UUID]:
    residence_id = authenticated.principal.primary_residence_id
    if residence_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="primary residence is required",
        )
    return (
        authenticated.principal.installation_id,
        residence_id,
        authenticated.principal.operator_id,
    )


def _invalid_request() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="invalid financial cash flow request",
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="financial account was not found",
    )


def _parameters(
    request: Request,
) -> tuple[date | None, date | None, tuple[UUID, ...] | None, str | None]:
    """Strict query: known names only, singletons once, explicit formats."""
    items = request.query_params.multi_items()
    names = [name for name, _ in items]
    if not set(names) <= _PARAMETERS:
        raise _invalid_request()
    for name in _SINGLE_PARAMETERS:
        if names.count(name) > 1:
            raise _invalid_request()
    values = dict(item for item in items if item[0] in _SINGLE_PARAMETERS)
    raw_accounts = [value for name, value in items if name == "accountId"]
    if len(raw_accounts) > CASH_FLOW_ACCOUNTS_MAX:
        raise _invalid_request()
    account_ids: tuple[UUID, ...] | None = None
    if raw_accounts:
        parsed: list[UUID] = []
        for raw in raw_accounts:
            if not _UUID_PATTERN.fullmatch(raw):
                raise _invalid_request()
            try:
                parsed.append(validate_financial_resource_id(UUID(raw)))
            except (TypeError, ValueError):
                # Well formed but never a resource id: as unknown as any other.
                raise _not_found() from None
        if len(set(parsed)) != len(parsed):
            raise _invalid_request()
        account_ids = tuple(parsed)
    currency = values.get("currency")
    if currency is not None and not _CURRENCY_PATTERN.fullmatch(currency):
        raise _invalid_request()
    return (
        _date(values.get("from")),
        _date(values.get("through")),
        account_ids,
        currency,
    )


def _date(value: str | None) -> date | None:
    if value is None:
        return None
    if not _DATE_PATTERN.fullmatch(value):
        raise _invalid_request()
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _invalid_request() from None


def _money(value: Money) -> CashFlowMoneyResponse:
    return CashFlowMoneyResponse(amount=value.canonical_amount, currency=value.currency)


def _optional_money(value: Money | None) -> CashFlowMoneyResponse | None:
    return None if value is None else _money(value)


def _risk(risk: FinancialCashFlowRisk) -> CashFlowRiskResponse:
    return CashFlowRiskResponse(
        minimum_balance=_money(risk.minimum_balance),
        minimum_balance_date=risk.minimum_balance_date,
        first_negative_date=risk.first_negative_date,
        negative_days=risk.negative_days,
    )


def _issue(issue: FinancialCashFlowIssue) -> CashFlowIssueResponse:
    return CashFlowIssueResponse(
        code=issue.code.value,
        severity=issue.severity.value,
        count=issue.count,
        account_ids=issue.account_ids,
    )


def _totals(totals: FinancialCashFlowTotals) -> CashFlowTotalsResponse:
    return CashFlowTotalsResponse(
        realized_income=_money(totals.realized_income),
        realized_expense=_money(totals.realized_expense),
        neutral_in=_money(totals.neutral_in),
        neutral_out=_money(totals.neutral_out),
        realized_net=_money(totals.realized_net),
        expected_income=_money(totals.expected_income),
        expected_expense=_money(totals.expected_expense),
        expected_net=_money(totals.expected_net),
        overdue_count=totals.overdue_count,
        overdue_net=_money(totals.overdue_net),
        recurrence_realized_count=totals.recurrence_realized_count,
        recurrence_realized_expected=_money(totals.recurrence_realized_expected),
        recurrence_realized_actual=_money(totals.recurrence_realized_actual),
        realized_count=totals.realized_count,
        expected_count=totals.expected_count,
    )


def _account(summary: FinancialCashFlowAccountSummary) -> CashFlowAccountResponse:
    account = summary.account
    opening = summary.opening_balance
    return CashFlowAccountResponse(
        account_id=account.id,
        name=account.name,
        account_type=account.account_type.value,
        visibility_scope=account.visibility_scope.value,
        status=account.status.value,
        has_opening_balance=opening is not None,
        opening_balance_date=None if opening is None else opening.effective_date,
        starting_balance=_money(summary.starting_balance),
        balance_at_reference=_money(summary.balance_at_reference),
        realized_net=_money(summary.realized_net),
        expected_net=_money(summary.expected_net),
        closing_balance=_money(summary.closing_balance),
        risk=_risk(summary.risk),
    )


def _day(day: FinancialCashFlowDay) -> CashFlowDayResponse:
    return CashFlowDayResponse(
        date=day.date,
        opening=_money(day.opening),
        realized_income=_money(day.realized_income),
        realized_expense=_money(day.realized_expense),
        expected_income=_money(day.expected_income),
        expected_expense=_money(day.expected_expense),
        neutral_net=_money(day.neutral_net),
        closing=_money(day.closing),
        projected=day.projected,
        negative=day.negative,
    )


def _event(event: FinancialCashFlowEvent) -> CashFlowEventResponse:
    return CashFlowEventResponse(
        date=event.date,
        kind=event.kind.value,
        account_id=event.account_id,
        amount=_money(event.amount),
        result_effect=event.result_effect.value,
        description=event.description,
        movement_id=event.movement_id,
        movement_role=None
        if event.movement_role is None
        else event.movement_role.value,
        reversal_of_id=event.reversal_of_id,
        transfer_id=event.transfer_id,
        occurrence_id=event.occurrence_id,
        recurrence_id=event.recurrence_id,
        rule_version=event.rule_version,
        period_start=event.period_start,
        scheduled_date=event.scheduled_date,
        overdue=event.overdue,
        expected_amount=_optional_money(event.expected_amount),
        balance_after=_money(event.balance_after),
        account_balance_after=_money(event.account_balance_after),
    )


def _group(group: FinancialCashFlowGroup) -> CashFlowGroupResponse:
    return CashFlowGroupResponse(
        currency=group.currency,
        projection_status=group.projection_status.value,
        issues=tuple(_issue(issue) for issue in group.issues),
        starting_balance=_money(group.starting_balance),
        balance_at_reference=_money(group.balance_at_reference),
        closing_balance=_money(group.closing_balance),
        totals=_totals(group.totals),
        risk=_risk(group.risk),
        accounts=tuple(_account(summary) for summary in group.accounts),
        days=tuple(_day(day) for day in group.days),
        events=tuple(_event(event) for event in group.events),
    )


def _response(projection: FinancialCashFlowProjection) -> CashFlowResponse:
    window = projection.window
    return CashFlowResponse(
        reference_date=window.reference_date,
        from_date=window.from_date,
        through_date=window.through_date,
        days=window.days,
        calculated_at=projection.calculated_at,
        excluded_sources=tuple(source.value for source in projection.excluded_sources),
        groups=tuple(_group(group) for group in projection.groups),
    )


def _raise_error(error: Exception) -> NoReturn:
    """Map every persistence failure to a sanitized, non-leaking response."""
    if isinstance(error, FinancialCashFlowAccountNotFoundError):
        raise _not_found() from None
    if isinstance(error, FinancialCashFlowAccessError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="financial access denied",
        ) from None
    if isinstance(error, FinancialCashFlowLimitExceededError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="financial cash flow window has too many events",
        ) from None
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="financial service is unavailable",
    ) from None


@router.get("/cash-flow", response_model=CashFlowResponse)
def read_cash_flow(
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> CashFlowResponse:
    from_date, through_date, account_ids, currency = _parameters(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        projection = _service(request).read_cash_flow(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            from_date=from_date,
            through_date=through_date,
            account_ids=account_ids,
            currency=currency,
        )
    except CashFlowRequestError:
        raise _invalid_request() from None
    except FinancialCashFlowPersistenceError as error:
        _raise_error(error)
    return _response(projection)


__all__ = ["router"]
