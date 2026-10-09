"""Authenticated project-planning and auditable expense-link API (#262).

Planning is not the ledger. All realized amounts derive from the server's
canonical Movements. No DELETE and no implicit money transfer or budget write.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from meufinanceiro_finance import (
    FinancialProjectDraft,
    FinancialProjectLinkRevisionDraft,
    FinancialProjectLinkRevisionRecord,
    FinancialProjectReplacement,
    FinancialVisibilityScope,
    Money,
    validate_financial_idempotency_key,
    validate_financial_resource_id,
)
from meufinanceiro_persistence.financial_project_store import (
    FinancialProjectAccessError,
    FinancialProjectConflictError,
    FinancialProjectLimitError,
    FinancialProjectNotEditableError,
    FinancialProjectNotFoundError,
    FinancialProjectPersistenceError,
)
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import AuthenticatedOperatorRequest, require_primary_residence
from app.services.financial_projects import (
    FinancialProjectService,
    ProjectSummaryView,
    ProjectView,
)

router = APIRouter(prefix="/finance", tags=["finance"])
_AMOUNT_RE = re.compile(r"^(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,8})?$")
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class ProjectMoneyResponse(BaseModel):
    amount: str
    currency: str


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    idempotency_key: UUID = Field(alias="idempotencyKey")
    title: str = Field(strict=True, min_length=1, max_length=96)
    description: str | None = Field(default=None, strict=True, max_length=280)
    visibility_scope: str = Field(
        alias="visibilityScope", strict=True, min_length=1, max_length=16
    )
    currency: str = Field(strict=True, min_length=3, max_length=3)
    planned_amount: str = Field(
        alias="plannedAmount", strict=True, min_length=1, max_length=32
    )
    target_date: str | None = Field(
        alias="targetDate", default=None, strict=True, min_length=10, max_length=10
    )


class ProjectReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    expected_version: int = Field(alias="expectedVersion", strict=True, ge=1)
    title: str = Field(strict=True, min_length=1, max_length=96)
    description: str | None = Field(default=None, strict=True, max_length=280)
    currency: str = Field(strict=True, min_length=3, max_length=3)
    planned_amount: str = Field(
        alias="plannedAmount", strict=True, min_length=1, max_length=32
    )
    target_date: str | None = Field(
        alias="targetDate", default=None, strict=True, min_length=10, max_length=10
    )


class ProjectLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    idempotency_key: UUID = Field(alias="idempotencyKey")
    project_id: UUID | None = Field(alias="projectId")
    expected_predecessor_id: UUID | None = Field(alias="expectedPredecessorId")


class ProjectResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    owner_operator_id: UUID = Field(serialization_alias="ownerOperatorId")
    visibility_scope: str = Field(serialization_alias="visibilityScope")
    title: str
    description: str | None
    currency: str
    planned: ProjectMoneyResponse
    target_date: date | None = Field(serialization_alias="targetDate")
    version: int
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")
    can_edit: bool = Field(serialization_alias="canEdit")


class ProjectsResponse(BaseModel):
    items: tuple[ProjectResponse, ...]


class ProjectLinkResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    movement_id: UUID = Field(serialization_alias="movementId")
    project_id: UUID | None = Field(serialization_alias="projectId")
    supersedes_id: UUID | None = Field(serialization_alias="supersedesId")
    revision: int
    actor_operator_id: UUID = Field(serialization_alias="actorOperatorId")
    created_at: datetime = Field(serialization_alias="createdAt")


class ProjectCurrentLinkResponse(BaseModel):
    link: ProjectLinkResponse | None


class ProjectLinkHistoryResponse(BaseModel):
    items: tuple[ProjectLinkResponse, ...]


class ProjectExpenseResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    movement_id: UUID = Field(serialization_alias="movementId")
    description: str | None
    effective_date: date = Field(serialization_alias="effectiveDate")
    original_amount: ProjectMoneyResponse = Field(serialization_alias="originalAmount")
    realized: ProjectMoneyResponse
    reversed: bool


class ProjectSummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project: ProjectResponse
    realized: ProjectMoneyResponse
    remaining: ProjectMoneyResponse
    excess: ProjectMoneyResponse
    progress_percent: str = Field(serialization_alias="progressPercent")
    progress_status: str = Field(serialization_alias="progressStatus")
    expense_count: int = Field(serialization_alias="expenseCount")
    expenses: tuple[ProjectExpenseResponse, ...]


def _service(request: Request) -> FinancialProjectService:
    service = getattr(request.app.state, "financial_projects", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="financial service is unavailable",
        )
    return cast(FinancialProjectService, service)


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
        detail="invalid financial project request",
    )


def _reject_query(request: Request) -> None:
    if request.query_params:
        raise _invalid_request()


def _id(value: UUID) -> UUID:
    try:
        return validate_financial_resource_id(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="financial resource was not found",
        ) from None


def _positive_money(value: str, currency: str) -> Money:
    if not _AMOUNT_RE.fullmatch(value):
        raise _invalid_request()
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount <= 0:
            raise InvalidOperation
        return Money(amount, currency)
    except (InvalidOperation, TypeError, ValueError):
        raise _invalid_request() from None


def _date(value: str | None) -> date | None:
    if value is None:
        return None
    if not _DATE_RE.fullmatch(value):
        raise _invalid_request()
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _invalid_request() from None


def _draft(payload: ProjectCreateRequest) -> FinancialProjectDraft:
    try:
        return FinancialProjectDraft(
            title=payload.title,
            description=payload.description,
            visibility_scope=FinancialVisibilityScope(payload.visibility_scope),
            planned=_positive_money(payload.planned_amount, payload.currency),
            target_date=_date(payload.target_date),
        )
    except HTTPException:
        raise
    except (TypeError, ValueError):
        raise _invalid_request() from None


def _replacement(payload: ProjectReplaceRequest) -> FinancialProjectReplacement:
    try:
        return FinancialProjectReplacement(
            expected_version=payload.expected_version,
            title=payload.title,
            description=payload.description,
            planned=_positive_money(payload.planned_amount, payload.currency),
            target_date=_date(payload.target_date),
        )
    except HTTPException:
        raise
    except (TypeError, ValueError):
        raise _invalid_request() from None


def _money(value: Money) -> ProjectMoneyResponse:
    return ProjectMoneyResponse(amount=value.canonical_amount, currency=value.currency)


def _project(view: ProjectView) -> ProjectResponse:
    p = view.project
    return ProjectResponse(
        id=p.id,
        owner_operator_id=p.owner_operator_id,
        visibility_scope=p.visibility_scope.value,
        title=p.title,
        description=p.description,
        currency=p.planned.currency,
        planned=_money(p.planned),
        target_date=p.target_date,
        version=p.version,
        created_at=p.created_at,
        updated_at=p.updated_at,
        can_edit=view.can_edit,
    )


def _link(record: FinancialProjectLinkRevisionRecord) -> ProjectLinkResponse:
    return ProjectLinkResponse(
        id=record.id,
        movement_id=record.movement_id,
        project_id=record.project_id,
        supersedes_id=record.supersedes_id,
        revision=record.revision,
        actor_operator_id=record.actor_operator_id,
        created_at=record.created_at,
    )


def _summary(view: ProjectSummaryView) -> ProjectSummaryResponse:
    s = view.summary
    return ProjectSummaryResponse(
        project=_project(ProjectView(s.project, view.can_edit)),
        realized=_money(s.realized),
        remaining=_money(s.remaining),
        excess=_money(s.excess),
        progress_percent=format(s.progress_percent, "f"),
        progress_status=s.progress_status.value,
        expense_count=s.expense_count,
        expenses=tuple(
            ProjectExpenseResponse(
                movement_id=f.original.id,
                description=f.original.description,
                effective_date=f.original.effective_date,
                original_amount=_money(-f.original.amount),
                realized=_money(f.realized),
                reversed=f.reversal is not None,
            )
            for f in view.expenses
        ),
    )


def _raise_error(error: FinancialProjectPersistenceError) -> NoReturn:
    if isinstance(error, FinancialProjectNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="financial resource was not found",
        ) from None
    if isinstance(
        error, (FinancialProjectAccessError, FinancialProjectNotEditableError)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="financial access denied",
        ) from None
    if isinstance(error, (FinancialProjectConflictError, FinancialProjectLimitError)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="financial project conflicts with canonical state",
        ) from None
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="financial service is unavailable",
    ) from None


@router.get("/projects", response_model=ProjectsResponse)
def list_projects(
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> ProjectsResponse:
    _reject_query(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        items = _service(request).list_projects(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
        )
    except FinancialProjectPersistenceError as error:
        _raise_error(error)
    return ProjectsResponse(items=tuple(_project(item) for item in items))


@router.post(
    "/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    payload: ProjectCreateRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> ProjectResponse:
    _reject_query(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        key = validate_financial_idempotency_key(payload.idempotency_key)
    except (TypeError, ValueError):
        raise _invalid_request() from None
    draft = _draft(payload)
    try:
        return _project(
            _service(request).create_project(
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=operator_id,
                idempotency_key=key,
                draft=draft,
            )
        )
    except FinancialProjectPersistenceError as error:
        _raise_error(error)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> ProjectResponse:
    _reject_query(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        return _project(
            _service(request).get_project(
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=operator_id,
                project_id=_id(project_id),
            )
        )
    except FinancialProjectPersistenceError as error:
        _raise_error(error)


@router.put("/projects/{project_id}", response_model=ProjectResponse)
def replace_project(
    project_id: UUID,
    payload: ProjectReplaceRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> ProjectResponse:
    _reject_query(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    replacement = _replacement(payload)
    try:
        return _project(
            _service(request).replace_project(
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=operator_id,
                project_id=_id(project_id),
                replacement=replacement,
            )
        )
    except FinancialProjectPersistenceError as error:
        _raise_error(error)


@router.get("/projects/{project_id}/summary", response_model=ProjectSummaryResponse)
def project_summary(
    project_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> ProjectSummaryResponse:
    _reject_query(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        return _summary(
            _service(request).summary(
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=operator_id,
                project_id=_id(project_id),
            )
        )
    except FinancialProjectPersistenceError as error:
        _raise_error(error)
    except (ValueError, TypeError, ArithmeticError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="financial service is unavailable",
        ) from None


@router.get(
    "/movements/{movement_id}/project-link",
    response_model=ProjectCurrentLinkResponse,
)
def get_movement_project_link(
    movement_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> ProjectCurrentLinkResponse:
    _reject_query(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        item = _service(request).get_link(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            movement_id=_id(movement_id),
        )
    except FinancialProjectPersistenceError as error:
        _raise_error(error)
    return ProjectCurrentLinkResponse(link=_link(item) if item else None)


@router.get(
    "/movements/{movement_id}/project-link/revisions",
    response_model=ProjectLinkHistoryResponse,
)
def movement_project_link_history(
    movement_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> ProjectLinkHistoryResponse:
    _reject_query(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        history = _service(request).read_link_history(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            movement_id=_id(movement_id),
        )
    except FinancialProjectPersistenceError as error:
        _raise_error(error)
    return ProjectLinkHistoryResponse(items=tuple(_link(x) for x in history))


@router.post(
    "/movements/{movement_id}/project-link",
    response_model=ProjectLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
def revise_movement_project_link(
    movement_id: UUID,
    payload: ProjectLinkRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> ProjectLinkResponse:
    _reject_query(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        key = validate_financial_idempotency_key(payload.idempotency_key)
        project_id = _id(payload.project_id) if payload.project_id is not None else None
        predecessor_id = (
            _id(payload.expected_predecessor_id)
            if payload.expected_predecessor_id is not None
            else None
        )
        draft = FinancialProjectLinkRevisionDraft(
            movement_id=_id(movement_id),
            project_id=project_id,
            expected_predecessor_id=predecessor_id,
        )
    except HTTPException:
        raise
    except (TypeError, ValueError):
        raise _invalid_request() from None
    try:
        result = _service(request).revise_link(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=key,
            draft=draft,
        )
    except FinancialProjectPersistenceError as error:
        _raise_error(error)
    return _link(result)


__all__ = ["router"]
