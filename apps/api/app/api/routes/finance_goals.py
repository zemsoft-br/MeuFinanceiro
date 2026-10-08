"""Authenticated financial goal routes (planning + virtual allocation, ADR-0029).

A goal is created, read, listed, CAS-edited and summarized, and the owner explicitly
allocates or releases virtual balance. An allocation is not a Movement, a transfer or
blocked money, and nothing here can write the ledger. There is deliberately no
``DELETE`` or ``PATCH``. Creates and allocations are replay-safe through explicit
idempotency keys; ``PUT`` requires ``expectedVersion`` and a stale version is a
``409`` with nothing written. Every payload is strict (unknown fields are a ``422``)
and every amount is a decimal string, never a float.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from meufinanceiro_finance import (
    FinancialGoalAccountSummary,
    FinancialGoalAllocationDraft,
    FinancialGoalDraft,
    FinancialGoalEventKind,
    FinancialGoalEventRecord,
    FinancialGoalRecord,
    FinancialGoalReplacement,
    FinancialVisibilityScope,
    Money,
    validate_financial_idempotency_key,
    validate_financial_resource_id,
)
from meufinanceiro_persistence.financial_goal_store import (
    FinancialGoalAccessError,
    FinancialGoalAccountNotFoundError,
    FinancialGoalAvailabilityError,
    FinancialGoalConflictError,
    FinancialGoalInvalidShapeError,
    FinancialGoalLimitError,
    FinancialGoalNotEditableError,
    FinancialGoalNotFoundError,
    FinancialGoalPersistenceError,
    FinancialGoalReleaseError,
    FinancialGoalVersionConflictError,
)
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import AuthenticatedOperatorRequest, require_primary_residence
from app.services.financial_goals import (
    FinancialGoalService,
    GoalListItem,
    GoalRequestError,
    GoalSummaryView,
    GoalView,
)

router = APIRouter(prefix="/finance", tags=["finance"])

_AMOUNT_PATTERN = re.compile(r"^(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,8})?$")
_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class GoalMoneyResponse(BaseModel):
    amount: str
    currency: str


class GoalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    idempotency_key: UUID = Field(alias="idempotencyKey")
    title: str = Field(strict=True, min_length=1, max_length=96)
    description: str | None = Field(default=None, strict=True, max_length=280)
    visibility_scope: str = Field(
        alias="visibilityScope", strict=True, min_length=1, max_length=16
    )
    currency: str = Field(strict=True, min_length=3, max_length=3)
    target_amount: str = Field(
        alias="targetAmount", strict=True, min_length=1, max_length=32
    )
    target_date: str | None = Field(
        default=None, alias="targetDate", strict=True, min_length=10, max_length=10
    )


class GoalReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    expected_version: int = Field(alias="expectedVersion", strict=True, ge=1)
    title: str = Field(strict=True, min_length=1, max_length=96)
    description: str | None = Field(default=None, strict=True, max_length=280)
    currency: str = Field(strict=True, min_length=3, max_length=3)
    target_amount: str = Field(
        alias="targetAmount", strict=True, min_length=1, max_length=32
    )
    target_date: str | None = Field(
        default=None, alias="targetDate", strict=True, min_length=10, max_length=10
    )


class GoalAllocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    idempotency_key: UUID = Field(alias="idempotencyKey")
    operation: str = Field(strict=True, min_length=1, max_length=16)
    account_id: UUID = Field(alias="accountId")
    amount: str = Field(strict=True, min_length=1, max_length=32)
    currency: str = Field(strict=True, min_length=3, max_length=3)


class GoalResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    owner_operator_id: UUID = Field(serialization_alias="ownerOperatorId")
    visibility_scope: str = Field(serialization_alias="visibilityScope")
    title: str
    description: str | None
    currency: str
    target: GoalMoneyResponse
    target_date: date | None = Field(serialization_alias="targetDate")
    version: int
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")
    can_edit: bool = Field(serialization_alias="canEdit")


class GoalListItemResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    goal: GoalResponse
    allocated: GoalMoneyResponse
    remaining_target: GoalMoneyResponse = Field(serialization_alias="remainingTarget")
    progress_percent: str = Field(serialization_alias="progressPercent")
    progress_status: str = Field(serialization_alias="progressStatus")


class GoalsResponse(BaseModel):
    items: tuple[GoalListItemResponse, ...]


class GoalEventResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    goal_id: UUID = Field(serialization_alias="goalId")
    account_id: UUID = Field(serialization_alias="accountId")
    operation: str
    amount: GoalMoneyResponse
    actor_operator_id: UUID = Field(serialization_alias="actorOperatorId")
    created_at: datetime = Field(serialization_alias="createdAt")


class GoalAccountSummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    account_id: UUID = Field(serialization_alias="accountId")
    account_status: str = Field(serialization_alias="accountStatus")
    allocated: GoalMoneyResponse
    account_balance: GoalMoneyResponse = Field(serialization_alias="accountBalance")
    account_allocated_total: GoalMoneyResponse = Field(
        serialization_alias="accountAllocatedTotal"
    )
    backing_status: str = Field(serialization_alias="backingStatus")
    shortfall: GoalMoneyResponse


class GoalSummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    goal: GoalResponse
    target: GoalMoneyResponse
    allocated: GoalMoneyResponse
    remaining_target: GoalMoneyResponse = Field(serialization_alias="remainingTarget")
    surplus: GoalMoneyResponse
    progress_percent: str = Field(serialization_alias="progressPercent")
    progress_status: str = Field(serialization_alias="progressStatus")
    has_insufficient_backing: bool = Field(serialization_alias="hasInsufficientBacking")
    accounts: tuple[GoalAccountSummaryResponse, ...]
    events: tuple[GoalEventResponse, ...]


def _service(request: Request) -> FinancialGoalService:
    service = getattr(request.app.state, "financial_goals", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="financial service is unavailable",
        )
    return cast(FinancialGoalService, service)


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
        detail="invalid financial goal request",
    )


def _reject_query_params(request: Request) -> None:
    if request.query_params:
        raise _invalid_request()


def _goal_id(value: UUID) -> UUID:
    try:
        return validate_financial_resource_id(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="financial resource was not found",
        ) from None


def _amount(value: str, currency: str) -> Money:
    if not _AMOUNT_PATTERN.fullmatch(value):
        raise _invalid_request()
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount <= 0:
            raise InvalidOperation
        return Money(amount, currency)
    except (InvalidOperation, TypeError, ValueError):
        raise _invalid_request() from None


def _target_date(value: str | None) -> date | None:
    if value is None:
        return None
    if not _DATE_PATTERN.fullmatch(value):
        raise _invalid_request()
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _invalid_request() from None


def _create_draft(payload: GoalCreateRequest) -> FinancialGoalDraft:
    try:
        return FinancialGoalDraft(
            title=payload.title,
            description=payload.description,
            visibility_scope=FinancialVisibilityScope(payload.visibility_scope),
            target=_amount(payload.target_amount, payload.currency),
            target_date=_target_date(payload.target_date),
        )
    except HTTPException:
        raise
    except (TypeError, ValueError):
        raise _invalid_request() from None


def _replacement(payload: GoalReplaceRequest) -> FinancialGoalReplacement:
    try:
        return FinancialGoalReplacement(
            expected_version=payload.expected_version,
            title=payload.title,
            description=payload.description,
            target=_amount(payload.target_amount, payload.currency),
            target_date=_target_date(payload.target_date),
        )
    except HTTPException:
        raise
    except (TypeError, ValueError):
        raise _invalid_request() from None


def _allocation_draft(payload: GoalAllocationRequest) -> FinancialGoalAllocationDraft:
    try:
        return FinancialGoalAllocationDraft(
            kind=FinancialGoalEventKind(payload.operation),
            account_id=payload.account_id,
            amount=_amount(payload.amount, payload.currency),
        )
    except HTTPException:
        raise
    except (TypeError, ValueError):
        raise _invalid_request() from None


def _money(value: Money) -> GoalMoneyResponse:
    return GoalMoneyResponse(amount=value.canonical_amount, currency=value.currency)


def _record_response(record: FinancialGoalRecord, *, can_edit: bool) -> GoalResponse:
    return GoalResponse(
        id=record.id,
        owner_operator_id=record.owner_operator_id,
        visibility_scope=record.visibility_scope.value,
        title=record.title,
        description=record.description,
        currency=record.currency,
        target=_money(record.target),
        target_date=record.target_date,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        can_edit=can_edit,
    )


def _goal_response(view: GoalView) -> GoalResponse:
    return _record_response(view.goal, can_edit=view.can_edit)


def _list_item_response(item: GoalListItem) -> GoalListItemResponse:
    return GoalListItemResponse(
        goal=_record_response(item.goal, can_edit=item.can_edit),
        allocated=_money(item.allocated),
        remaining_target=_money(item.remaining_target),
        progress_percent=format(item.progress_percent, "f"),
        progress_status=item.progress_status.value,
    )


def _event_response(event: FinancialGoalEventRecord) -> GoalEventResponse:
    return GoalEventResponse(
        id=event.id,
        goal_id=event.goal_id,
        account_id=event.account_id,
        operation=event.kind.value,
        amount=_money(event.amount),
        actor_operator_id=event.actor_operator_id,
        created_at=event.created_at,
    )


def _account_summary(
    account: FinancialGoalAccountSummary,
) -> GoalAccountSummaryResponse:
    return GoalAccountSummaryResponse(
        account_id=account.account_id,
        account_status=account.account_status.value,
        allocated=_money(account.allocated),
        account_balance=_money(account.account_balance),
        account_allocated_total=_money(account.account_allocated_total),
        backing_status=account.backing_status.value,
        shortfall=_money(account.shortfall),
    )


def _summary_response(view: GoalSummaryView) -> GoalSummaryResponse:
    summary = view.summary
    return GoalSummaryResponse(
        goal=_record_response(summary.goal, can_edit=view.can_edit),
        target=_money(summary.goal.target),
        allocated=_money(summary.allocated),
        remaining_target=_money(summary.remaining_target),
        surplus=_money(summary.surplus),
        progress_percent=format(summary.progress_percent, "f"),
        progress_status=summary.progress_status.value,
        has_insufficient_backing=summary.has_insufficient_backing,
        accounts=tuple(_account_summary(account) for account in summary.accounts),
        events=tuple(_event_response(event) for event in summary.events),
    )


def _raise_error(error: Exception) -> NoReturn:
    """Map every persistence failure to a sanitized, non-leaking response."""
    if isinstance(error, FinancialGoalNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="financial resource was not found",
        ) from None
    if isinstance(error, FinancialGoalAccountNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="financial account was not found",
        ) from None
    if isinstance(error, (FinancialGoalAccessError, FinancialGoalNotEditableError)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="financial access denied",
        ) from None
    if isinstance(error, FinancialGoalVersionConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="financial goal version is stale",
        ) from None
    if isinstance(error, FinancialGoalAvailabilityError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="financial goal allocation exceeds the available balance",
        ) from None
    if isinstance(error, FinancialGoalReleaseError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="financial goal release exceeds the allocated amount",
        ) from None
    if isinstance(error, FinancialGoalLimitError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="financial goal limit reached",
        ) from None
    if isinstance(error, FinancialGoalConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="financial goal conflicts with canonical state",
        ) from None
    if isinstance(error, FinancialGoalInvalidShapeError):
        raise _invalid_request() from None
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="financial service is unavailable",
    ) from None


@router.get("/goals", response_model=GoalsResponse)
def list_goals(
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> GoalsResponse:
    # No pagination, search or filter in v1: the list is bounded server-side.
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        items = _service(request).list_goals(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
        )
    except FinancialGoalPersistenceError as error:
        _raise_error(error)
    return GoalsResponse(items=tuple(_list_item_response(item) for item in items))


@router.post("/goals", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
def create_goal(
    payload: GoalCreateRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> GoalResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        idempotency_key = validate_financial_idempotency_key(payload.idempotency_key)
    except (TypeError, ValueError):
        raise _invalid_request() from None
    draft = _create_draft(payload)
    try:
        view = _service(request).create_goal(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=idempotency_key,
            draft=draft,
        )
    except GoalRequestError:
        raise _invalid_request() from None
    except FinancialGoalPersistenceError as error:
        _raise_error(error)
    return _goal_response(view)


@router.get("/goals/{goal_id}", response_model=GoalResponse)
def get_goal(
    goal_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> GoalResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        view = _service(request).get_goal(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            goal_id=_goal_id(goal_id),
        )
    except FinancialGoalPersistenceError as error:
        _raise_error(error)
    return _goal_response(view)


@router.put("/goals/{goal_id}", response_model=GoalResponse)
def replace_goal(
    goal_id: UUID,
    payload: GoalReplaceRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> GoalResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    replacement = _replacement(payload)
    try:
        view = _service(request).replace_goal(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            goal_id=_goal_id(goal_id),
            replacement=replacement,
        )
    except GoalRequestError:
        raise _invalid_request() from None
    except FinancialGoalPersistenceError as error:
        _raise_error(error)
    return _goal_response(view)


@router.get("/goals/{goal_id}/summary", response_model=GoalSummaryResponse)
def get_goal_summary(
    goal_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> GoalSummaryResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        view = _service(request).summary(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            goal_id=_goal_id(goal_id),
        )
    except FinancialGoalPersistenceError as error:
        _raise_error(error)
    except ValueError:
        # A stored state that violates a domain bound is never shown truncated.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="financial service is unavailable",
        ) from None
    return _summary_response(view)


@router.post(
    "/goals/{goal_id}/allocations",
    response_model=GoalEventResponse,
    status_code=status.HTTP_201_CREATED,
)
def allocate_goal(
    goal_id: UUID,
    payload: GoalAllocationRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> GoalEventResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        idempotency_key = validate_financial_idempotency_key(payload.idempotency_key)
        validate_financial_resource_id(payload.account_id)
    except (TypeError, ValueError):
        raise _invalid_request() from None
    draft = _allocation_draft(payload)
    try:
        event = _service(request).allocate(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            goal_id=_goal_id(goal_id),
            idempotency_key=idempotency_key,
            draft=draft,
        )
    except FinancialGoalPersistenceError as error:
        _raise_error(error)
    return _event_response(event)


__all__ = ["router"]
