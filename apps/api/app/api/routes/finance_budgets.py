"""Authenticated monthly budget routes (planning, never a second ledger).

A budget is created, read, listed, CAS-edited and summarized. There is
deliberately no ``DELETE`` or ``PATCH``. Create is replay-safe through an explicit
idempotency key; ``PUT`` requires ``expectedVersion`` and a stale version is a
``409`` with nothing written. The realized amounts in the summary are derived on
every read from the ledger and the current classification.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from meufinanceiro_finance import (
    BUDGET_LINES_MAX,
    FinancialBudgetCoverage,
    FinancialBudgetDateBasis,
    FinancialBudgetDraft,
    FinancialBudgetLineDraft,
    FinancialBudgetLineSummary,
    FinancialBudgetRecord,
    FinancialBudgetReplacement,
    FinancialResultEffect,
    FinancialVisibilityScope,
    Money,
    parse_budget_period,
    validate_financial_idempotency_key,
    validate_financial_resource_id,
)
from meufinanceiro_persistence.financial_budget_store import (
    FinancialBudgetAccessError,
    FinancialBudgetCategoryNotFoundError,
    FinancialBudgetConflictError,
    FinancialBudgetInvalidShapeError,
    FinancialBudgetNotEditableError,
    FinancialBudgetNotFoundError,
    FinancialBudgetPersistenceError,
    FinancialBudgetVersionConflictError,
)
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import AuthenticatedOperatorRequest, require_primary_residence
from app.services.financial_budgets import (
    BudgetRequestError,
    BudgetSummaryView,
    BudgetView,
    FinancialBudgetService,
)

router = APIRouter(prefix="/finance", tags=["finance"])

_PLANNED_PATTERN = re.compile(r"^(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,8})?$")
_PERIOD_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}$")


class BudgetMoneyResponse(BaseModel):
    amount: str
    currency: str


class BudgetLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    category_id: UUID = Field(alias="categoryId")
    result_effect: str = Field(
        alias="resultEffect", strict=True, min_length=1, max_length=16
    )
    planned_amount: str = Field(
        alias="plannedAmount", strict=True, min_length=1, max_length=32
    )


class BudgetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    idempotency_key: UUID = Field(alias="idempotencyKey")
    name: str = Field(strict=True, min_length=1, max_length=96)
    visibility_scope: str = Field(
        alias="visibilityScope", strict=True, min_length=1, max_length=16
    )
    currency: str = Field(strict=True, min_length=3, max_length=3)
    period: str = Field(strict=True, min_length=7, max_length=7)
    date_basis: str = Field(alias="dateBasis", strict=True, min_length=1, max_length=16)
    lines: list[BudgetLineRequest] = Field(min_length=1, max_length=BUDGET_LINES_MAX)


class BudgetReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    expected_version: int = Field(alias="expectedVersion", strict=True, ge=1)
    name: str = Field(strict=True, min_length=1, max_length=96)
    currency: str = Field(strict=True, min_length=3, max_length=3)
    lines: list[BudgetLineRequest] = Field(min_length=1, max_length=BUDGET_LINES_MAX)


class BudgetLineResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category_id: UUID = Field(serialization_alias="categoryId")
    result_effect: str = Field(serialization_alias="resultEffect")
    planned: BudgetMoneyResponse


class BudgetResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    owner_operator_id: UUID = Field(serialization_alias="ownerOperatorId")
    visibility_scope: str = Field(serialization_alias="visibilityScope")
    name: str
    currency: str
    period_kind: str = Field(serialization_alias="periodKind")
    period_start: date = Field(serialization_alias="periodStart")
    period_end: date = Field(serialization_alias="periodEnd")
    date_basis: str = Field(serialization_alias="dateBasis")
    realization_account_scope: str = Field(
        serialization_alias="realizationAccountScope"
    )
    version: int
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")
    can_edit: bool = Field(serialization_alias="canEdit")
    lines: tuple[BudgetLineResponse, ...]


class BudgetsResponse(BaseModel):
    items: tuple[BudgetResponse, ...]


class BudgetLineSummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category_id: UUID = Field(serialization_alias="categoryId")
    result_effect: str = Field(serialization_alias="resultEffect")
    planned: BudgetMoneyResponse
    realized: BudgetMoneyResponse
    remaining: BudgetMoneyResponse
    status: str
    progress_percent: str = Field(serialization_alias="progressPercent")


class BudgetCoverageResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    unclassified_expense_count: int = Field(
        serialization_alias="unclassifiedExpenseCount"
    )
    unclassified_expense_amount: BudgetMoneyResponse = Field(
        serialization_alias="unclassifiedExpenseAmount"
    )
    unclassified_income_count: int = Field(
        serialization_alias="unclassifiedIncomeCount"
    )
    unclassified_income_amount: BudgetMoneyResponse = Field(
        serialization_alias="unclassifiedIncomeAmount"
    )


class BudgetSummaryResponse(BaseModel):
    budget: BudgetResponse
    lines: tuple[BudgetLineSummaryResponse, ...]
    coverage: BudgetCoverageResponse


def _service(request: Request) -> FinancialBudgetService:
    service = getattr(request.app.state, "financial_budgets", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="financial service is unavailable",
        )
    return cast(FinancialBudgetService, service)


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
        detail="invalid financial budget request",
    )


def _reject_query_params(request: Request) -> None:
    if request.query_params:
        raise _invalid_request()


def _budget_id(value: UUID) -> UUID:
    try:
        return validate_financial_resource_id(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="financial resource was not found",
        ) from None


def _planned(value: str, currency: str) -> Money:
    if not _PLANNED_PATTERN.fullmatch(value):
        raise _invalid_request()
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount <= 0:
            raise InvalidOperation
        return Money(amount, currency)
    except (InvalidOperation, TypeError, ValueError):
        raise _invalid_request() from None


def _lines(
    payload_lines: list[BudgetLineRequest], currency: str
) -> tuple[FinancialBudgetLineDraft, ...]:
    try:
        return tuple(
            FinancialBudgetLineDraft(
                category_id=line.category_id,
                result_effect=FinancialResultEffect(line.result_effect),
                planned=_planned(line.planned_amount, currency),
            )
            for line in payload_lines
        )
    except HTTPException:
        raise
    except (TypeError, ValueError):
        raise _invalid_request() from None


def _create_draft(payload: BudgetCreateRequest) -> FinancialBudgetDraft:
    if not _PERIOD_PATTERN.fullmatch(payload.period):
        raise _invalid_request()
    try:
        return FinancialBudgetDraft(
            name=payload.name,
            visibility_scope=FinancialVisibilityScope(payload.visibility_scope),
            currency=payload.currency,
            period_start=parse_budget_period(payload.period),
            date_basis=FinancialBudgetDateBasis(payload.date_basis),
            lines=_lines(payload.lines, payload.currency),
        )
    except HTTPException:
        raise
    except (TypeError, ValueError):
        raise _invalid_request() from None


def _replacement(payload: BudgetReplaceRequest) -> FinancialBudgetReplacement:
    try:
        return FinancialBudgetReplacement(
            expected_version=payload.expected_version,
            name=payload.name,
            lines=_lines(payload.lines, payload.currency),
        )
    except HTTPException:
        raise
    except (TypeError, ValueError):
        raise _invalid_request() from None


def _money(value: Money) -> BudgetMoneyResponse:
    return BudgetMoneyResponse(amount=value.canonical_amount, currency=value.currency)


def _budget_response(view: BudgetView) -> BudgetResponse:
    return _record_response(view.budget, can_edit=view.can_edit)


def _record_response(
    record: FinancialBudgetRecord, *, can_edit: bool
) -> BudgetResponse:
    return BudgetResponse(
        id=record.id,
        owner_operator_id=record.owner_operator_id,
        visibility_scope=record.visibility_scope.value,
        name=record.name,
        currency=record.currency,
        period_kind=record.period_kind.value,
        period_start=record.period_start,
        period_end=record.period_end,
        date_basis=record.date_basis.value,
        realization_account_scope=record.realization_account_scope.value,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        can_edit=can_edit,
        lines=tuple(
            BudgetLineResponse(
                category_id=line.category_id,
                result_effect=line.result_effect.value,
                planned=_money(line.planned),
            )
            for line in record.lines
        ),
    )


def _line_summary(line: FinancialBudgetLineSummary) -> BudgetLineSummaryResponse:
    return BudgetLineSummaryResponse(
        category_id=line.category_id,
        result_effect=line.result_effect.value,
        planned=_money(line.planned),
        realized=_money(line.realized),
        remaining=_money(line.remaining),
        status=line.status.value,
        progress_percent=format(line.progress_percent, "f"),
    )


def _coverage(coverage: FinancialBudgetCoverage) -> BudgetCoverageResponse:
    return BudgetCoverageResponse(
        unclassified_expense_count=coverage.unclassified_expense_count,
        unclassified_expense_amount=_money(coverage.unclassified_expense),
        unclassified_income_count=coverage.unclassified_income_count,
        unclassified_income_amount=_money(coverage.unclassified_income),
    )


def _summary_response(view: BudgetSummaryView) -> BudgetSummaryResponse:
    summary = view.summary
    return BudgetSummaryResponse(
        budget=_record_response(summary.budget, can_edit=view.can_edit),
        lines=tuple(_line_summary(line) for line in summary.lines),
        coverage=_coverage(summary.coverage),
    )


def _raise_error(error: Exception) -> NoReturn:
    """Map every persistence failure to a sanitized, non-leaking response."""
    if isinstance(error, FinancialBudgetNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="financial resource was not found",
        ) from None
    if isinstance(error, FinancialBudgetCategoryNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="financial category was not found",
        ) from None
    if isinstance(error, (FinancialBudgetAccessError, FinancialBudgetNotEditableError)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="financial access denied",
        ) from None
    if isinstance(error, FinancialBudgetVersionConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="financial budget version is stale",
        ) from None
    if isinstance(error, FinancialBudgetConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="financial budget conflicts with canonical state",
        ) from None
    if isinstance(error, FinancialBudgetInvalidShapeError):
        raise _invalid_request() from None
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="financial service is unavailable",
    ) from None


@router.get("/budgets", response_model=BudgetsResponse)
def list_budgets(
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
    period: Annotated[str, Query(min_length=7, max_length=7)],
) -> BudgetsResponse:
    # Only ``period`` is accepted: pagination, search and filters are not part of v1.
    if set(request.query_params) != {"period"} or not _PERIOD_PATTERN.fullmatch(period):
        raise _invalid_request()
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        views = _service(request).list_budgets(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            period=period,
        )
    except BudgetRequestError:
        raise _invalid_request() from None
    except FinancialBudgetPersistenceError as error:
        _raise_error(error)
    return BudgetsResponse(items=tuple(_budget_response(view) for view in views))


@router.post(
    "/budgets",
    response_model=BudgetResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_budget(
    payload: BudgetCreateRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> BudgetResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        idempotency_key = validate_financial_idempotency_key(payload.idempotency_key)
    except (TypeError, ValueError):
        raise _invalid_request() from None
    draft = _create_draft(payload)
    try:
        view = _service(request).create_budget(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=idempotency_key,
            draft=draft,
        )
    except FinancialBudgetPersistenceError as error:
        _raise_error(error)
    return _budget_response(view)


@router.get("/budgets/{budget_id}", response_model=BudgetResponse)
def get_budget(
    budget_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> BudgetResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        view = _service(request).get_budget(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            budget_id=_budget_id(budget_id),
        )
    except FinancialBudgetPersistenceError as error:
        _raise_error(error)
    return _budget_response(view)


@router.put("/budgets/{budget_id}", response_model=BudgetResponse)
def replace_budget(
    budget_id: UUID,
    payload: BudgetReplaceRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> BudgetResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    replacement = _replacement(payload)
    try:
        view = _service(request).replace_budget(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            budget_id=_budget_id(budget_id),
            replacement=replacement,
        )
    except FinancialBudgetPersistenceError as error:
        _raise_error(error)
    return _budget_response(view)


@router.get("/budgets/{budget_id}/summary", response_model=BudgetSummaryResponse)
def get_budget_summary(
    budget_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> BudgetSummaryResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        view = _service(request).summary(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            budget_id=_budget_id(budget_id),
        )
    except FinancialBudgetPersistenceError as error:
        _raise_error(error)
    return _summary_response(view)


__all__ = ["router"]
