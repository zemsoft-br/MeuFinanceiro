"""Authenticated manual monthly recurrence routes (planning, never a second ledger).

A recurrence is created, read, listed, CAS-edited, paused and resumed; its
occurrences are generated explicitly, listed and skipped. There is deliberately no
``DELETE`` or ``PATCH``. Create is replay-safe through an explicit idempotency key;
``PUT`` requires ``expectedVersion`` and a stale version is a ``409`` with nothing
written. Nothing here creates a Movement or moves a balance.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from meufinanceiro_finance import (
    FinancialOccurrenceStatus,
    FinancialRecurrenceDraft,
    FinancialRecurrenceOccurrenceRecord,
    FinancialRecurrenceRealization,
    FinancialRecurrenceRealizationDraft,
    FinancialRecurrenceRecord,
    FinancialRecurrenceReplacement,
    FinancialRecurrenceStatus,
    FinancialResultEffect,
    Money,
    validate_financial_idempotency_key,
    validate_financial_resource_id,
)
from meufinanceiro_persistence.financial_recurrence_store import (
    FinancialRecurrenceAccessError,
    FinancialRecurrenceAccountNotFoundError,
    FinancialRecurrenceBeforeOpeningBalanceError,
    FinancialRecurrenceConflictError,
    FinancialRecurrenceInvalidShapeError,
    FinancialRecurrenceNotEditableError,
    FinancialRecurrenceNotFoundError,
    FinancialRecurrenceOccurrenceNotFoundError,
    FinancialRecurrenceOccurrenceStateError,
    FinancialRecurrencePausedError,
    FinancialRecurrencePersistenceError,
    FinancialRecurrenceVersionConflictError,
)
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import AuthenticatedOperatorRequest, require_primary_residence
from app.services.financial_recurrences import (
    FinancialRecurrenceService,
    OccurrenceGenerationView,
    OccurrenceView,
    RecurrenceEditView,
    RecurrenceRequestError,
    RecurrenceView,
)

router = APIRouter(prefix="/finance", tags=["finance"])

_AMOUNT_PATTERN = re.compile(r"^(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,8})?$")
_PERIOD_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}$")
_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class RecurrenceMoneyResponse(BaseModel):
    amount: str
    currency: str


class RecurrenceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    idempotency_key: UUID = Field(alias="idempotencyKey")
    account_id: UUID = Field(alias="accountId")
    description: str = Field(strict=True, min_length=1, max_length=256)
    result_effect: str = Field(
        alias="resultEffect", strict=True, min_length=1, max_length=16
    )
    expected_amount: str = Field(
        alias="expectedAmount", strict=True, min_length=1, max_length=32
    )
    currency: str = Field(strict=True, min_length=3, max_length=3)
    start_date: str = Field(
        alias="startDate", strict=True, min_length=10, max_length=10
    )
    day_of_month: int = Field(alias="dayOfMonth", strict=True, ge=1, le=31)
    end_date: str | None = Field(
        default=None, alias="endDate", strict=True, min_length=10, max_length=10
    )


class RecurrenceReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    expected_version: int = Field(alias="expectedVersion", strict=True, ge=1)
    description: str = Field(strict=True, min_length=1, max_length=256)
    expected_amount: str = Field(
        alias="expectedAmount", strict=True, min_length=1, max_length=32
    )
    day_of_month: int = Field(alias="dayOfMonth", strict=True, ge=1, le=31)
    end_date: str | None = Field(
        default=None, alias="endDate", strict=True, min_length=10, max_length=10
    )


class OccurrenceGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_period: str = Field(
        alias="fromPeriod", strict=True, min_length=7, max_length=7
    )
    through_period: str = Field(
        alias="throughPeriod", strict=True, min_length=7, max_length=7
    )


class OccurrenceRealizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    idempotency_key: UUID = Field(alias="idempotencyKey")
    actual_amount: str = Field(
        alias="actualAmount", strict=True, min_length=1, max_length=32
    )
    currency: str = Field(strict=True, min_length=3, max_length=3)
    effective_date: str = Field(
        alias="effectiveDate", strict=True, min_length=10, max_length=10
    )
    competence_date: str = Field(
        alias="competenceDate", strict=True, min_length=10, max_length=10
    )


class RecurrenceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    account_id: UUID = Field(serialization_alias="accountId")
    owner_operator_id: UUID = Field(serialization_alias="ownerOperatorId")
    description: str
    result_effect: str = Field(serialization_alias="resultEffect")
    expected: RecurrenceMoneyResponse
    frequency: str
    start_date: date = Field(serialization_alias="startDate")
    day_of_month: int = Field(serialization_alias="dayOfMonth")
    end_date: date | None = Field(serialization_alias="endDate")
    status: str
    version: int
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")
    can_edit: bool = Field(serialization_alias="canEdit")


class RecurrenceEditResponse(RecurrenceResponse):
    superseded_count: int = Field(serialization_alias="supersededCount")


class RecurrencesResponse(BaseModel):
    items: tuple[RecurrenceResponse, ...]


class OccurrenceRealizationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    movement_id: UUID = Field(serialization_alias="movementId")
    actual: RecurrenceMoneyResponse
    effective_date: date = Field(serialization_alias="effectiveDate")
    competence_date: date = Field(serialization_alias="competenceDate")
    realized_at: datetime = Field(serialization_alias="realizedAt")
    movement_state: str = Field(serialization_alias="movementState")


class OccurrenceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    recurrence_id: UUID = Field(serialization_alias="recurrenceId")
    account_id: UUID = Field(serialization_alias="accountId")
    owner_operator_id: UUID = Field(serialization_alias="ownerOperatorId")
    period_start: date = Field(serialization_alias="periodStart")
    scheduled_date: date = Field(serialization_alias="scheduledDate")
    rule_version: int = Field(serialization_alias="ruleVersion")
    result_effect: str = Field(serialization_alias="resultEffect")
    expected: RecurrenceMoneyResponse
    description: str
    status: str
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")
    can_edit: bool = Field(serialization_alias="canEdit")
    realization: OccurrenceRealizationResponse | None


class OccurrencesResponse(BaseModel):
    items: tuple[OccurrenceResponse, ...]


class OccurrenceGenerationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    created_count: int = Field(serialization_alias="createdCount")
    items: tuple[OccurrenceResponse, ...]


def _service(request: Request) -> FinancialRecurrenceService:
    service = getattr(request.app.state, "financial_recurrences", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="financial service is unavailable",
        )
    return cast(FinancialRecurrenceService, service)


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
        detail="invalid financial recurrence request",
    )


def _reject_query_params(
    request: Request, allowed: frozenset[str] = frozenset()
) -> None:
    if set(request.query_params) - allowed:
        raise _invalid_request()


def _resource_id(value: UUID) -> UUID:
    try:
        return validate_financial_resource_id(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="financial resource was not found",
        ) from None


def _plain_date(value: str) -> date:
    if not _DATE_PATTERN.fullmatch(value):
        raise _invalid_request()
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _invalid_request() from None


def _positive_amount(value: str) -> Decimal:
    if not _AMOUNT_PATTERN.fullmatch(value):
        raise _invalid_request()
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount <= 0:
            raise InvalidOperation
        return amount
    except InvalidOperation:
        raise _invalid_request() from None


def _create_draft(payload: RecurrenceCreateRequest) -> FinancialRecurrenceDraft:
    try:
        return FinancialRecurrenceDraft(
            account_id=payload.account_id,
            description=payload.description,
            result_effect=FinancialResultEffect(payload.result_effect),
            expected=Money(_positive_amount(payload.expected_amount), payload.currency),
            start_date=_plain_date(payload.start_date),
            day_of_month=payload.day_of_month,
            end_date=(
                _plain_date(payload.end_date) if payload.end_date is not None else None
            ),
        )
    except HTTPException:
        raise
    except (TypeError, ValueError):
        raise _invalid_request() from None


def _replacement(payload: RecurrenceReplaceRequest) -> FinancialRecurrenceReplacement:
    try:
        return FinancialRecurrenceReplacement(
            expected_version=payload.expected_version,
            description=payload.description,
            expected_amount=_positive_amount(payload.expected_amount),
            day_of_month=payload.day_of_month,
            end_date=(
                _plain_date(payload.end_date) if payload.end_date is not None else None
            ),
        )
    except HTTPException:
        raise
    except (TypeError, ValueError):
        raise _invalid_request() from None


def _realization_draft(
    payload: OccurrenceRealizeRequest,
) -> FinancialRecurrenceRealizationDraft:
    try:
        return FinancialRecurrenceRealizationDraft(
            actual=Money(_positive_amount(payload.actual_amount), payload.currency),
            effective_date=_plain_date(payload.effective_date),
            competence_date=_plain_date(payload.competence_date),
        )
    except HTTPException:
        raise
    except (TypeError, ValueError):
        raise _invalid_request() from None


def _money(value: Money) -> RecurrenceMoneyResponse:
    return RecurrenceMoneyResponse(
        amount=value.canonical_amount, currency=value.currency
    )


def _recurrence_fields(
    record: FinancialRecurrenceRecord, can_edit: bool
) -> dict[str, object]:
    return {
        "id": record.id,
        "account_id": record.account_id,
        "owner_operator_id": record.owner_operator_id,
        "description": record.description,
        "result_effect": record.result_effect.value,
        "expected": _money(record.expected),
        "frequency": record.frequency.value,
        "start_date": record.start_date,
        "day_of_month": record.day_of_month,
        "end_date": record.end_date,
        "status": record.status.value,
        "version": record.version,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "can_edit": can_edit,
    }


def _recurrence_response(view: RecurrenceView) -> RecurrenceResponse:
    return RecurrenceResponse(**_recurrence_fields(view.recurrence, view.can_edit))  # type: ignore[arg-type]


def _edit_response(view: RecurrenceEditView) -> RecurrenceEditResponse:
    return RecurrenceEditResponse(
        **_recurrence_fields(view.view.recurrence, view.view.can_edit),  # type: ignore[arg-type]
        superseded_count=view.superseded_count,
    )


def _realization(
    value: FinancialRecurrenceRealization | None,
) -> OccurrenceRealizationResponse | None:
    if value is None:
        return None
    return OccurrenceRealizationResponse(
        movement_id=value.movement_id,
        actual=_money(value.actual),
        effective_date=value.effective_date,
        competence_date=value.competence_date,
        realized_at=value.realized_at,
        movement_state=value.movement_state.value,
    )


def _occurrence_response(view: OccurrenceView) -> OccurrenceResponse:
    record: FinancialRecurrenceOccurrenceRecord = view.occurrence
    return OccurrenceResponse(
        id=record.id,
        recurrence_id=record.recurrence_id,
        account_id=record.account_id,
        owner_operator_id=record.owner_operator_id,
        period_start=record.period_start,
        scheduled_date=record.scheduled_date,
        rule_version=record.rule_version,
        result_effect=record.result_effect.value,
        expected=_money(record.expected),
        description=record.description,
        status=record.status.value,
        created_at=record.created_at,
        updated_at=record.updated_at,
        can_edit=view.can_edit,
        realization=_realization(record.realization),
    )


def _generation_response(
    view: OccurrenceGenerationView,
) -> OccurrenceGenerationResponse:
    return OccurrenceGenerationResponse(
        created_count=view.created_count,
        items=tuple(_occurrence_response(item) for item in view.items),
    )


def _raise_error(error: Exception) -> NoReturn:
    """Map every persistence failure to a sanitized, non-leaking response."""
    if isinstance(
        error,
        (FinancialRecurrenceNotFoundError, FinancialRecurrenceOccurrenceNotFoundError),
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="financial resource was not found",
        ) from None
    if isinstance(error, FinancialRecurrenceAccountNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="financial account was not found",
        ) from None
    if isinstance(
        error, (FinancialRecurrenceAccessError, FinancialRecurrenceNotEditableError)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="financial access denied",
        ) from None
    if isinstance(error, FinancialRecurrenceVersionConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="financial recurrence version is stale",
        ) from None
    if isinstance(error, FinancialRecurrencePausedError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="financial recurrence is paused",
        ) from None
    if isinstance(error, FinancialRecurrenceOccurrenceStateError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="financial recurrence occurrence state does not allow this operation",
        ) from None
    if isinstance(error, FinancialRecurrenceBeforeOpeningBalanceError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="financial operation precedes opening balance",
        ) from None
    if isinstance(error, FinancialRecurrenceConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="financial recurrence conflicts with canonical state",
        ) from None
    if isinstance(error, FinancialRecurrenceInvalidShapeError):
        raise _invalid_request() from None
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="financial service is unavailable",
    ) from None


def _status_filter(value: str | None) -> FinancialRecurrenceStatus | None:
    if value is None:
        return None
    try:
        return FinancialRecurrenceStatus(value)
    except ValueError:
        raise _invalid_request() from None


@router.get("/recurrences", response_model=RecurrencesResponse)
def list_recurrences(
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
    recurrence_status: Annotated[
        str | None, Query(alias="status", min_length=1, max_length=16)
    ] = None,
) -> RecurrencesResponse:
    _reject_query_params(request, frozenset({"status"}))
    installation_id, residence_id, operator_id = _context(authenticated)
    filter_status = _status_filter(recurrence_status)
    try:
        views = _service(request).list_recurrences(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            status=filter_status,
        )
    except FinancialRecurrencePersistenceError as error:
        _raise_error(error)
    return RecurrencesResponse(items=tuple(_recurrence_response(v) for v in views))


@router.post(
    "/recurrences",
    response_model=RecurrenceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_recurrence(
    payload: RecurrenceCreateRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> RecurrenceResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        idempotency_key = validate_financial_idempotency_key(payload.idempotency_key)
    except (TypeError, ValueError):
        raise _invalid_request() from None
    draft = _create_draft(payload)
    try:
        view = _service(request).create_recurrence(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=idempotency_key,
            draft=draft,
        )
    except FinancialRecurrencePersistenceError as error:
        _raise_error(error)
    return _recurrence_response(view)


@router.get("/recurrences/{recurrence_id}", response_model=RecurrenceResponse)
def get_recurrence(
    recurrence_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> RecurrenceResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        view = _service(request).get_recurrence(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            recurrence_id=_resource_id(recurrence_id),
        )
    except FinancialRecurrencePersistenceError as error:
        _raise_error(error)
    return _recurrence_response(view)


@router.put("/recurrences/{recurrence_id}", response_model=RecurrenceEditResponse)
def replace_recurrence(
    recurrence_id: UUID,
    payload: RecurrenceReplaceRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> RecurrenceEditResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    replacement = _replacement(payload)
    try:
        view = _service(request).replace_recurrence(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            recurrence_id=_resource_id(recurrence_id),
            replacement=replacement,
        )
    except FinancialRecurrencePersistenceError as error:
        _raise_error(error)
    return _edit_response(view)


@router.post("/recurrences/{recurrence_id}/pause", response_model=RecurrenceResponse)
def pause_recurrence(
    recurrence_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> RecurrenceResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        view = _service(request).pause_recurrence(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            recurrence_id=_resource_id(recurrence_id),
        )
    except FinancialRecurrencePersistenceError as error:
        _raise_error(error)
    return _recurrence_response(view)


@router.post("/recurrences/{recurrence_id}/resume", response_model=RecurrenceResponse)
def resume_recurrence(
    recurrence_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> RecurrenceResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        view = _service(request).resume_recurrence(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            recurrence_id=_resource_id(recurrence_id),
        )
    except FinancialRecurrencePersistenceError as error:
        _raise_error(error)
    return _recurrence_response(view)


@router.post(
    "/recurrences/{recurrence_id}/occurrences/generate",
    response_model=OccurrenceGenerationResponse,
)
def generate_occurrences(
    recurrence_id: UUID,
    payload: OccurrenceGenerateRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> OccurrenceGenerationResponse:
    _reject_query_params(request)
    if not (
        _PERIOD_PATTERN.fullmatch(payload.from_period)
        and _PERIOD_PATTERN.fullmatch(payload.through_period)
    ):
        raise _invalid_request()
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        view = _service(request).generate_occurrences(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            recurrence_id=_resource_id(recurrence_id),
            from_period=payload.from_period,
            through_period=payload.through_period,
        )
    except RecurrenceRequestError:
        raise _invalid_request() from None
    except FinancialRecurrencePersistenceError as error:
        _raise_error(error)
    return _generation_response(view)


@router.get("/recurrence-occurrences", response_model=OccurrencesResponse)
def list_occurrences(
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
    from_period: Annotated[str, Query(alias="fromPeriod", min_length=7, max_length=7)],
    through_period: Annotated[
        str, Query(alias="throughPeriod", min_length=7, max_length=7)
    ],
    recurrence_id: Annotated[UUID | None, Query(alias="recurrenceId")] = None,
    occurrence_status: Annotated[
        str | None, Query(alias="status", min_length=1, max_length=16)
    ] = None,
) -> OccurrencesResponse:
    _reject_query_params(
        request, frozenset({"fromPeriod", "throughPeriod", "recurrenceId", "status"})
    )
    if not (
        _PERIOD_PATTERN.fullmatch(from_period)
        and _PERIOD_PATTERN.fullmatch(through_period)
    ):
        raise _invalid_request()
    try:
        status_filter = (
            FinancialOccurrenceStatus(occurrence_status)
            if occurrence_status is not None
            else None
        )
    except ValueError:
        raise _invalid_request() from None
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        views = _service(request).list_occurrences(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            from_period=from_period,
            through_period=through_period,
            recurrence_id=(
                _resource_id(recurrence_id) if recurrence_id is not None else None
            ),
            status=status_filter,
        )
    except RecurrenceRequestError:
        raise _invalid_request() from None
    except FinancialRecurrencePersistenceError as error:
        _raise_error(error)
    return OccurrencesResponse(items=tuple(_occurrence_response(v) for v in views))


@router.post(
    "/recurrence-occurrences/{occurrence_id}/skip",
    response_model=OccurrenceResponse,
)
def skip_occurrence(
    occurrence_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> OccurrenceResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        view = _service(request).skip_occurrence(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            occurrence_id=_resource_id(occurrence_id),
        )
    except FinancialRecurrencePersistenceError as error:
        _raise_error(error)
    return _occurrence_response(view)


@router.post(
    "/recurrence-occurrences/{occurrence_id}/realize",
    response_model=OccurrenceResponse,
)
def realize_occurrence(
    occurrence_id: UUID,
    payload: OccurrenceRealizeRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> OccurrenceResponse:
    """Register one PENDING occurrence: exactly one canonical Movement, atomically."""
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        idempotency_key = validate_financial_idempotency_key(payload.idempotency_key)
    except (TypeError, ValueError):
        raise _invalid_request() from None
    draft = _realization_draft(payload)
    try:
        view = _service(request).realize_occurrence(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            occurrence_id=_resource_id(occurrence_id),
            idempotency_key=idempotency_key,
            draft=draft,
        )
    except FinancialRecurrencePersistenceError as error:
        _raise_error(error)
    return _occurrence_response(view)


__all__ = ["router"]
