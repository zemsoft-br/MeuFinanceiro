"""Authenticated deterministic categorization-rule routes.

Rules are created and disabled, never edited: there is deliberately no PUT, PATCH
or DELETE. Preview never writes; apply is an explicit operator action whose
confirmed Movement/rule pairs are re-validated against canonical state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from meufinanceiro_finance import (
    FinancialCategorizationApplyResult,
    FinancialCategorizationMatcher,
    FinancialCategorizationRuleDraft,
    FinancialCategorizationRuleRecord,
    FinancialMovementAllocationRuleOrigin,
    FinancialResultEffect,
    validate_financial_idempotency_key,
    validate_financial_resource_id,
)
from meufinanceiro_persistence.financial_account_store import (
    FinancialAccountAccessError,
    FinancialAccountNotFoundError,
    FinancialAccountPersistenceError,
)
from meufinanceiro_persistence.financial_categorization_rule_store import (
    FinancialCategorizationRuleAccessError,
    FinancialCategorizationRuleAccountNotFoundError,
    FinancialCategorizationRuleCategoryNotFoundError,
    FinancialCategorizationRuleConflictError,
    FinancialCategorizationRuleNotFoundError,
    FinancialCategorizationRulePersistenceError,
)
from meufinanceiro_persistence.financial_movement_allocation_store import (
    FinancialMovementAllocationPersistenceError,
)
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementAccessError,
    FinancialMovementAccountNotFoundError,
    FinancialMovementNotFoundError,
    FinancialMovementPersistenceError,
)
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import AuthenticatedOperatorRequest, require_primary_residence
from app.services.financial_categorization import (
    MAX_APPLY_ITEMS,
    CategorizationApplyOutcome,
    CategorizationApplyRequestItem,
    CategorizationPreview,
    FinancialCategorizationService,
)

router = APIRouter(prefix="/finance", tags=["finance"])

_PRIORITY_MIN = 1
_PRIORITY_MAX = 1000


class CategorizationRuleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    idempotency_key: UUID = Field(alias="idempotencyKey")
    description_matcher: str = Field(
        alias="descriptionMatcher", strict=True, min_length=1, max_length=16
    )
    description_pattern: str = Field(
        alias="descriptionPattern", strict=True, min_length=1, max_length=256
    )
    target_category_id: UUID = Field(alias="targetCategoryId")
    priority: int = Field(strict=True, ge=_PRIORITY_MIN, le=_PRIORITY_MAX)
    account_id: UUID | None = Field(default=None, alias="accountId")
    result_effect: str | None = Field(
        default=None, alias="resultEffect", strict=True, min_length=1, max_length=16
    )


class CategorizationRuleResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    rule_id: UUID = Field(serialization_alias="ruleId")
    created_by_operator_id: UUID = Field(serialization_alias="createdByOperatorId")
    account_id: UUID | None = Field(serialization_alias="accountId")
    result_effect: str | None = Field(serialization_alias="resultEffect")
    description_matcher: str = Field(serialization_alias="descriptionMatcher")
    description_pattern: str = Field(serialization_alias="descriptionPattern")
    target_category_id: UUID = Field(serialization_alias="targetCategoryId")
    priority: int
    status: str
    created_at: datetime = Field(serialization_alias="createdAt")
    disabled_at: datetime | None = Field(serialization_alias="disabledAt")


class CategorizationRulesResponse(BaseModel):
    rules: tuple[CategorizationRuleResponse, ...]


class CategorizationPreviewCountsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    matched: int
    no_match: int = Field(serialization_alias="noMatch")
    ambiguous: int
    ineligible: int
    already_classified: int = Field(serialization_alias="alreadyClassified")


class CategorizationPreviewItemResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    movement_id: UUID = Field(serialization_alias="movementId")
    status: str
    rule_id: UUID | None = Field(serialization_alias="ruleId")
    target_category_id: UUID | None = Field(serialization_alias="targetCategoryId")


class CategorizationPreviewResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    account_id: UUID = Field(serialization_alias="accountId")
    total_movements: int = Field(serialization_alias="totalMovements")
    counts: CategorizationPreviewCountsResponse
    items: tuple[CategorizationPreviewItemResponse, ...]
    items_truncated: bool = Field(serialization_alias="itemsTruncated")


class CategorizationApplyItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    movement_id: UUID = Field(alias="movementId")
    rule_id: UUID = Field(alias="ruleId")


class CategorizationApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    items: tuple[CategorizationApplyItemRequest, ...] = Field(
        min_length=1, max_length=MAX_APPLY_ITEMS
    )


class CategorizationApplyCountsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    classified: int
    already_classified: int = Field(serialization_alias="alreadyClassified")
    ambiguous: int
    no_match: int = Field(serialization_alias="noMatch")
    ineligible: int
    conflict: int
    failed: int


class CategorizationApplyResultResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    movement_id: UUID = Field(serialization_alias="movementId")
    status: str
    rule_id: UUID | None = Field(serialization_alias="ruleId")
    allocation_set_id: UUID | None = Field(serialization_alias="allocationSetId")


class CategorizationApplyResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    account_id: UUID = Field(serialization_alias="accountId")
    requested: int
    counts: CategorizationApplyCountsResponse
    results: tuple[CategorizationApplyResultResponse, ...]


class CategorizationRuleOriginResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    movement_id: UUID = Field(serialization_alias="movementId")
    allocation_set_id: UUID = Field(serialization_alias="allocationSetId")
    rule_id: UUID = Field(serialization_alias="ruleId")
    created_at: datetime = Field(serialization_alias="createdAt")


class CategorizationRuleOriginsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    account_id: UUID = Field(serialization_alias="accountId")
    origins: tuple[CategorizationRuleOriginResponse, ...]


def _service(request: Request) -> FinancialCategorizationService:
    service = getattr(request.app.state, "financial_categorization", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="financial service is unavailable",
        )
    return cast(FinancialCategorizationService, service)


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


def _reject_query_params(request: Request) -> None:
    if request.query_params:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="query parameters are not allowed",
        )


def _validated_resource_id(value: UUID) -> UUID:
    try:
        return validate_financial_resource_id(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="financial resource was not found",
        ) from None


def _invalid_request() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="invalid financial categorization request",
    )


def _rule_draft(
    payload: CategorizationRuleCreateRequest,
) -> FinancialCategorizationRuleDraft:
    try:
        return FinancialCategorizationRuleDraft(
            description_matcher=FinancialCategorizationMatcher(
                payload.description_matcher
            ),
            description_pattern=payload.description_pattern,
            target_category_id=payload.target_category_id,
            priority=payload.priority,
            account_id=payload.account_id,
            result_effect=(
                FinancialResultEffect(payload.result_effect)
                if payload.result_effect is not None
                else None
            ),
        )
    except (TypeError, ValueError):
        raise _invalid_request() from None


def _rule_response(
    record: FinancialCategorizationRuleRecord,
) -> CategorizationRuleResponse:
    return CategorizationRuleResponse(
        rule_id=record.id,
        created_by_operator_id=record.created_by_operator_id,
        account_id=record.account_id,
        result_effect=(
            record.result_effect.value if record.result_effect is not None else None
        ),
        description_matcher=record.description_matcher.value,
        description_pattern=record.description_pattern,
        target_category_id=record.target_category_id,
        priority=record.priority,
        status=record.status.value,
        created_at=record.created_at,
        disabled_at=record.disabled_at,
    )


def _preview_response(preview: CategorizationPreview) -> CategorizationPreviewResponse:
    counts = {status_.value: count for status_, count in preview.counts.items()}
    return CategorizationPreviewResponse(
        account_id=preview.account_id,
        total_movements=preview.total_movements,
        counts=CategorizationPreviewCountsResponse(
            matched=counts["MATCHED"],
            no_match=counts["NO_MATCH"],
            ambiguous=counts["AMBIGUOUS"],
            ineligible=counts["INELIGIBLE"],
            already_classified=counts["ALREADY_CLASSIFIED"],
        ),
        items=tuple(
            CategorizationPreviewItemResponse(
                movement_id=item.movement_id,
                status=item.status.value,
                rule_id=item.rule_id,
                target_category_id=item.target_category_id,
            )
            for item in preview.items
        ),
        items_truncated=preview.items_truncated,
    )


def _apply_result_response(
    result: FinancialCategorizationApplyResult,
) -> CategorizationApplyResultResponse:
    return CategorizationApplyResultResponse(
        movement_id=result.movement_id,
        status=result.status.value,
        rule_id=result.rule_id,
        allocation_set_id=result.allocation_set_id,
    )


def _apply_response(outcome: CategorizationApplyOutcome) -> CategorizationApplyResponse:
    counts = {status_.value: count for status_, count in outcome.counts.items()}
    return CategorizationApplyResponse(
        account_id=outcome.account_id,
        requested=outcome.requested,
        counts=CategorizationApplyCountsResponse(
            classified=counts["CLASSIFIED"],
            already_classified=counts["ALREADY_CLASSIFIED"],
            ambiguous=counts["AMBIGUOUS"],
            no_match=counts["NO_MATCH"],
            ineligible=counts["INELIGIBLE"],
            conflict=counts["CONFLICT"],
            failed=counts["FAILED"],
        ),
        results=tuple(_apply_result_response(item) for item in outcome.results),
    )


def _origin_response(
    origin: FinancialMovementAllocationRuleOrigin,
) -> CategorizationRuleOriginResponse:
    return CategorizationRuleOriginResponse(
        movement_id=origin.movement_id,
        allocation_set_id=origin.allocation_set_id,
        rule_id=origin.rule_id,
        created_at=origin.created_at,
    )


def _raise_error(error: Exception) -> NoReturn:
    """Map every persistence failure to a sanitized, non-leaking response."""
    if isinstance(
        error,
        (
            FinancialCategorizationRuleNotFoundError,
            FinancialCategorizationRuleAccountNotFoundError,
            FinancialAccountNotFoundError,
            FinancialMovementAccountNotFoundError,
            FinancialMovementNotFoundError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="financial resource was not found",
        ) from None
    if isinstance(error, FinancialCategorizationRuleCategoryNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="financial category was not found",
        ) from None
    if isinstance(
        error,
        (
            FinancialCategorizationRuleAccessError,
            FinancialAccountAccessError,
            FinancialMovementAccessError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="financial access denied",
        ) from None
    if isinstance(error, FinancialCategorizationRuleConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="financial operation conflicts with canonical state",
        ) from None
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="financial service is unavailable",
    ) from None


_PERSISTENCE_ERRORS = (
    FinancialCategorizationRulePersistenceError,
    FinancialAccountPersistenceError,
    FinancialMovementPersistenceError,
    FinancialMovementAllocationPersistenceError,
)


@router.get("/categorization-rules", response_model=CategorizationRulesResponse)
def list_categorization_rules(
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> CategorizationRulesResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        records = _service(request).list_rules(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
        )
    except _PERSISTENCE_ERRORS as error:
        _raise_error(error)
    return CategorizationRulesResponse(
        rules=tuple(_rule_response(item) for item in records)
    )


@router.post(
    "/categorization-rules",
    response_model=CategorizationRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_categorization_rule(
    payload: CategorizationRuleCreateRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> CategorizationRuleResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        idempotency_key = validate_financial_idempotency_key(payload.idempotency_key)
    except (TypeError, ValueError):
        raise _invalid_request() from None
    draft = _rule_draft(payload)
    try:
        record = _service(request).create_rule(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=idempotency_key,
            draft=draft,
        )
    except _PERSISTENCE_ERRORS as error:
        _raise_error(error)
    return _rule_response(record)


@router.post(
    "/categorization-rules/{rule_id}/disable",
    response_model=CategorizationRuleResponse,
)
def disable_categorization_rule(
    rule_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> CategorizationRuleResponse:
    _reject_query_params(request)
    rule_id = _validated_resource_id(rule_id)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        record = _service(request).disable_rule(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            rule_id=rule_id,
        )
    except _PERSISTENCE_ERRORS as error:
        _raise_error(error)
    return _rule_response(record)


@router.post(
    "/accounts/{account_id}/categorization-rules/preview",
    response_model=CategorizationPreviewResponse,
)
def preview_categorization_rules(
    account_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> CategorizationPreviewResponse:
    _reject_query_params(request)
    account_id = _validated_resource_id(account_id)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        preview = _service(request).preview(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )
    except _PERSISTENCE_ERRORS as error:
        _raise_error(error)
    return _preview_response(preview)


@router.post(
    "/accounts/{account_id}/categorization-rules/apply",
    response_model=CategorizationApplyResponse,
)
def apply_categorization_rules(
    account_id: UUID,
    payload: CategorizationApplyRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> CategorizationApplyResponse:
    _reject_query_params(request)
    account_id = _validated_resource_id(account_id)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        items = tuple(
            CategorizationApplyRequestItem(
                movement_id=validate_financial_resource_id(item.movement_id),
                rule_id=validate_financial_resource_id(item.rule_id),
            )
            for item in payload.items
        )
    except (TypeError, ValueError):
        raise _invalid_request() from None
    if len({item.movement_id for item in items}) != len(items):
        raise _invalid_request()
    try:
        outcome = _service(request).apply(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
            items=items,
        )
    except _PERSISTENCE_ERRORS as error:
        _raise_error(error)
    return _apply_response(outcome)


@router.get(
    "/accounts/{account_id}/categorization-rules/origins",
    response_model=CategorizationRuleOriginsResponse,
)
def list_categorization_rule_origins(
    account_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
) -> CategorizationRuleOriginsResponse:
    _reject_query_params(request)
    account_id = _validated_resource_id(account_id)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        origins = _service(request).list_rule_origins(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )
    except _PERSISTENCE_ERRORS as error:
        _raise_error(error)
    return CategorizationRuleOriginsResponse(
        account_id=account_id,
        origins=tuple(_origin_response(item) for item in origins),
    )


__all__ = ["router"]
