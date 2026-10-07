"""Authenticated assisted recurrence suggestion routes (derived, never a ledger).

``GET`` derives the operator's suggestions from realized, visible Movements and writes
nothing. ``dismiss`` and ``accept`` are explicit commands that re-run the detector for
the caller: a fingerprint is only an identity the server recomputes. ``accept``
creates exactly one canonical recurrence (and its provenance) and never a Movement or
an occurrence. There is deliberately no ``DELETE``, ``PUT`` or ``PATCH``.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from meufinanceiro_finance import (
    FinancialRecurrenceSuggestionAcceptance,
    FinancialRecurrenceSuggestionDecisionRecord,
    FinancialRecurrenceSuggestionEvidence,
    Money,
    validate_financial_idempotency_key,
    validate_recurrence_suggestion_fingerprint,
)
from meufinanceiro_persistence.financial_recurrence_store import (
    FinancialRecurrencePersistenceError,
)
from meufinanceiro_persistence.financial_recurrence_suggestion_store import (
    FinancialRecurrenceSuggestionConflictError,
    FinancialRecurrenceSuggestionLimitError,
    FinancialRecurrenceSuggestionNotAvailableError,
    FinancialRecurrenceSuggestionNotEditableError,
)
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import AuthenticatedOperatorRequest, require_primary_residence
from app.api.routes.finance_recurrences import (
    RecurrenceMoneyResponse,
    RecurrenceResponse,
    _raise_error as _raise_recurrence_error,
    _recurrence_fields,
)
from app.services.financial_recurrence_suggestions import (
    FinancialRecurrenceSuggestionService,
    SuggestionAcceptView,
    SuggestionDecisionView,
    SuggestionListView,
    SuggestionView,
)

router = APIRouter(prefix="/finance", tags=["finance"])

_AMOUNT_PATTERN = re.compile(r"^(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,8})?$")
_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class SuggestionAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    idempotency_key: UUID = Field(alias="idempotencyKey")
    description: str = Field(strict=True, min_length=1, max_length=256)
    expected_amount: str = Field(
        alias="expectedAmount", strict=True, min_length=1, max_length=32
    )
    start_date: str = Field(
        alias="startDate", strict=True, min_length=10, max_length=10
    )
    day_of_month: int = Field(alias="dayOfMonth", strict=True, ge=1, le=31)
    end_date: str | None = Field(
        default=None, alias="endDate", strict=True, min_length=10, max_length=10
    )


class SuggestionEvidenceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    movement_id: UUID = Field(serialization_alias="movementId")
    effective_date: date = Field(serialization_alias="effectiveDate")
    amount: RecurrenceMoneyResponse


class SuggestionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    fingerprint: str
    account_id: UUID = Field(serialization_alias="accountId")
    description: str
    normalized_description: str = Field(serialization_alias="normalizedDescription")
    currency: str
    evidence: tuple[SuggestionEvidenceResponse, ...]
    movement_ids: tuple[UUID, ...] = Field(serialization_alias="movementIds")
    observed_dates: tuple[date, ...] = Field(serialization_alias="observedDates")
    observed_amounts: tuple[RecurrenceMoneyResponse, ...] = Field(
        serialization_alias="observedAmounts"
    )
    suggested_day_of_month: int = Field(serialization_alias="suggestedDayOfMonth")
    suggested_expected_amount: RecurrenceMoneyResponse = Field(
        serialization_alias="suggestedExpectedAmount"
    )
    amount_behavior: str = Field(serialization_alias="amountBehavior")
    min_amount: RecurrenceMoneyResponse = Field(serialization_alias="minAmount")
    max_amount: RecurrenceMoneyResponse = Field(serialization_alias="maxAmount")
    last_amount: RecurrenceMoneyResponse = Field(serialization_alias="lastAmount")
    reason_codes: tuple[str, ...] = Field(serialization_alias="reasonCodes")
    can_accept: bool = Field(serialization_alias="canAccept")


class SuggestionsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    window_from: date = Field(serialization_alias="windowFrom")
    window_through: date = Field(serialization_alias="windowThrough")
    items: tuple[SuggestionResponse, ...]


class SuggestionDecisionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    fingerprint: str
    account_id: UUID = Field(serialization_alias="accountId")
    decision: str
    recurrence_id: UUID | None = Field(serialization_alias="recurrenceId")
    decided_at: datetime = Field(serialization_alias="decidedAt")
    created: bool


class SuggestionAcceptResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    recurrence: RecurrenceResponse
    decision: SuggestionDecisionResponse


def _service(request: Request) -> FinancialRecurrenceSuggestionService:
    service = getattr(request.app.state, "financial_recurrence_suggestions", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="financial service is unavailable",
        )
    return cast(FinancialRecurrenceSuggestionService, service)


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
        detail="invalid financial recurrence suggestion request",
    )


def _reject_query_params(request: Request) -> None:
    if set(request.query_params):
        raise _invalid_request()


def _fingerprint(value: str) -> str:
    try:
        return validate_recurrence_suggestion_fingerprint(value)
    except (TypeError, ValueError):
        raise _invalid_request() from None


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


def _acceptance(
    payload: SuggestionAcceptRequest,
) -> FinancialRecurrenceSuggestionAcceptance:
    try:
        return FinancialRecurrenceSuggestionAcceptance(
            description=payload.description,
            expected_amount=_positive_amount(payload.expected_amount),
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


def _money(value: Money) -> RecurrenceMoneyResponse:
    return RecurrenceMoneyResponse(
        amount=value.canonical_amount, currency=value.currency
    )


def _evidence(
    item: FinancialRecurrenceSuggestionEvidence, currency: str
) -> SuggestionEvidenceResponse:
    return SuggestionEvidenceResponse(
        movement_id=item.movement_id,
        effective_date=item.effective_date,
        amount=_money(Money(item.amount, currency)),
    )


def _suggestion_response(view: SuggestionView) -> SuggestionResponse:
    item = view.suggestion
    return SuggestionResponse(
        fingerprint=item.fingerprint,
        account_id=item.account_id,
        description=item.description,
        normalized_description=item.normalized_description,
        currency=item.currency,
        evidence=tuple(_evidence(entry, item.currency) for entry in item.evidence),
        movement_ids=item.movement_ids,
        observed_dates=item.observed_dates,
        observed_amounts=tuple(_money(amount) for amount in item.observed_amounts),
        suggested_day_of_month=item.suggested_day_of_month,
        suggested_expected_amount=_money(item.suggested_expected_amount),
        amount_behavior=item.amount_behavior.value,
        min_amount=_money(item.min_amount),
        max_amount=_money(item.max_amount),
        last_amount=_money(item.last_amount),
        reason_codes=tuple(code.value for code in item.reason_codes),
        can_accept=view.can_accept,
    )


def _decision_response(
    decision: FinancialRecurrenceSuggestionDecisionRecord, created: bool
) -> SuggestionDecisionResponse:
    return SuggestionDecisionResponse(
        fingerprint=decision.fingerprint,
        account_id=decision.account_id,
        decision=decision.decision.value,
        recurrence_id=decision.recurrence_id,
        decided_at=decision.decided_at,
        created=created,
    )


def _list_response(view: SuggestionListView) -> SuggestionsResponse:
    return SuggestionsResponse(
        window_from=view.window_from,
        window_through=view.window_through,
        items=tuple(_suggestion_response(item) for item in view.items),
    )


def _accept_response(view: SuggestionAcceptView) -> SuggestionAcceptResponse:
    return SuggestionAcceptResponse(
        recurrence=RecurrenceResponse(
            **_recurrence_fields(view.recurrence, view.can_edit)  # type: ignore[arg-type]
        ),
        decision=_decision_response(view.decision, view.created),
    )


def _raise_error(error: Exception) -> NoReturn:
    """Map every failure to a sanitized, non-leaking response."""
    if isinstance(error, FinancialRecurrenceSuggestionNotAvailableError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="financial recurrence suggestion is no longer available",
        ) from None
    if isinstance(error, FinancialRecurrenceSuggestionConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="financial recurrence suggestion conflicts with a recorded decision",
        ) from None
    if isinstance(error, FinancialRecurrenceSuggestionNotEditableError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="financial access denied",
        ) from None
    if isinstance(error, FinancialRecurrenceSuggestionLimitError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="financial recurrence suggestion limit reached",
        ) from None
    _raise_recurrence_error(error)


@router.get("/recurrence-suggestions", response_model=SuggestionsResponse)
def list_recurrence_suggestions(
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> SuggestionsResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        view = _service(request).list_suggestions(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
        )
    except FinancialRecurrencePersistenceError as error:
        _raise_error(error)
    return _list_response(view)


@router.post(
    "/recurrence-suggestions/{fingerprint}/dismiss",
    response_model=SuggestionDecisionResponse,
)
def dismiss_recurrence_suggestion(
    fingerprint: str,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> SuggestionDecisionResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    checked = _fingerprint(fingerprint)
    try:
        view: SuggestionDecisionView = _service(request).dismiss(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            fingerprint=checked,
        )
    except FinancialRecurrencePersistenceError as error:
        _raise_error(error)
    return _decision_response(view.decision, view.created)


@router.post(
    "/recurrence-suggestions/{fingerprint}/accept",
    response_model=SuggestionAcceptResponse,
    status_code=status.HTTP_201_CREATED,
)
def accept_recurrence_suggestion(
    fingerprint: str,
    payload: SuggestionAcceptRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> SuggestionAcceptResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    checked = _fingerprint(fingerprint)
    try:
        idempotency_key = validate_financial_idempotency_key(payload.idempotency_key)
    except (TypeError, ValueError):
        raise _invalid_request() from None
    acceptance = _acceptance(payload)
    try:
        view = _service(request).accept(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            fingerprint=checked,
            idempotency_key=idempotency_key,
            acceptance=acceptance,
        )
    except FinancialRecurrencePersistenceError as error:
        _raise_error(error)
    return _accept_response(view)
