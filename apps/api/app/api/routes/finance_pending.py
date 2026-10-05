"""Authenticated, read-only pending-classification inbox route.

The inbox is derived from the ledger and classification state at read time: there
is deliberately no write, status or dismissal endpoint here. Classifying an item
reuses the manual (#245) and rule-apply (#247) endpoints unchanged.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from meufinanceiro_finance import (
    PENDING_PAGE_LIMIT_DEFAULT,
    PENDING_PAGE_LIMIT_MAX,
    FinancialPendingMovementItem,
    FinancialPendingRuleStatus,
    FinancialResultEffect,
    Money,
    validate_financial_resource_id,
)
from meufinanceiro_persistence.financial_category_store import (
    FinancialCategoryAccessError,
    FinancialCategoryPersistenceError,
)
from meufinanceiro_persistence.financial_categorization_rule_store import (
    FinancialCategorizationRuleAccessError,
    FinancialCategorizationRulePersistenceError,
)
from meufinanceiro_persistence.financial_pending_movement_store import (
    FinancialPendingMovementAccessError,
    FinancialPendingMovementAccountNotFoundError,
    FinancialPendingMovementPersistenceError,
)
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import AuthenticatedOperatorRequest, require_primary_residence
from app.services.financial_pending_movements import (
    FinancialPendingMovementService,
    PendingMovementsPage,
    PendingMovementsRequestError,
)

router = APIRouter(prefix="/finance", tags=["finance"])

_ALLOWED_QUERY = frozenset(
    {"limit", "cursor", "accountId", "resultEffect", "ruleStatus"}
)


class PendingMoneyResponse(BaseModel):
    amount: str
    currency: str


class PendingMovementResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    movement_id: UUID = Field(serialization_alias="movementId")
    account_id: UUID = Field(serialization_alias="accountId")
    money: PendingMoneyResponse
    result_effect: str = Field(serialization_alias="resultEffect")
    effective_date: date = Field(serialization_alias="effectiveDate")
    competence_date: date = Field(serialization_alias="competenceDate")
    description: str | None
    account_visibility_scope: str = Field(serialization_alias="accountVisibilityScope")
    account_owner_operator_id: UUID = Field(
        serialization_alias="accountOwnerOperatorId"
    )
    can_classify: bool = Field(serialization_alias="canClassify")
    rule_status: str = Field(serialization_alias="ruleStatus")
    matched_rule_id: UUID | None = Field(serialization_alias="matchedRuleId")
    suggested_category_id: UUID | None = Field(
        serialization_alias="suggestedCategoryId"
    )


class PendingMovementsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: tuple[PendingMovementResponse, ...]
    next_cursor: str | None = Field(serialization_alias="nextCursor")


def _service(request: Request) -> FinancialPendingMovementService:
    service = getattr(request.app.state, "financial_pending", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="financial service is unavailable",
        )
    return cast(FinancialPendingMovementService, service)


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
        detail="invalid financial request",
    )


def _item_response(item: FinancialPendingMovementItem) -> PendingMovementResponse:
    movement = item.candidate.movement
    money: Money = movement.amount
    rule = item.rule
    return PendingMovementResponse(
        movement_id=movement.id,
        account_id=movement.account_id,
        money=PendingMoneyResponse(
            amount=money.canonical_amount, currency=money.currency
        ),
        result_effect=movement.result_effect.value,
        effective_date=movement.effective_date,
        competence_date=movement.competence_date,
        description=movement.description,
        account_visibility_scope=item.candidate.account_visibility_scope.value,
        account_owner_operator_id=item.candidate.account_owner_operator_id,
        can_classify=item.can_classify,
        rule_status=item.rule_status.value,
        matched_rule_id=rule.id if rule is not None else None,
        suggested_category_id=rule.target_category_id if rule is not None else None,
    )


def _page_response(page: PendingMovementsPage) -> PendingMovementsResponse:
    return PendingMovementsResponse(
        items=tuple(_item_response(item) for item in page.items),
        next_cursor=page.next_cursor,
    )


def _raise_error(error: Exception) -> NoReturn:
    """Map every persistence failure to a sanitized, non-leaking response."""
    if isinstance(error, FinancialPendingMovementAccountNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="financial resource was not found",
        ) from None
    if isinstance(
        error,
        (
            FinancialPendingMovementAccessError,
            FinancialCategorizationRuleAccessError,
            FinancialCategoryAccessError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="financial access denied",
        ) from None
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="financial service is unavailable",
    ) from None


_PERSISTENCE_ERRORS = (
    FinancialPendingMovementPersistenceError,
    FinancialCategorizationRulePersistenceError,
    FinancialCategoryPersistenceError,
)


@router.get("/pending-movements", response_model=PendingMovementsResponse)
def list_pending_movements(
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest, Depends(require_primary_residence)
    ],
    limit: Annotated[
        int, Query(ge=1, le=PENDING_PAGE_LIMIT_MAX)
    ] = PENDING_PAGE_LIMIT_DEFAULT,
    cursor: Annotated[str | None, Query(min_length=1, max_length=256)] = None,
    account_id: Annotated[UUID | None, Query(alias="accountId")] = None,
    result_effect: Annotated[
        Literal["INCOME", "EXPENSE"] | None, Query(alias="resultEffect")
    ] = None,
    rule_status: Annotated[
        Literal["MATCHED", "AMBIGUOUS", "NO_MATCH"] | None, Query(alias="ruleStatus")
    ] = None,
) -> PendingMovementsResponse:
    # Unknown parameters (``offset``, ``page``, ``search``...) are rejected so the
    # keyset cursor stays the only way to move through the inbox.
    if not set(request.query_params) <= _ALLOWED_QUERY:
        raise _invalid_request()
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        if account_id is not None:
            validate_financial_resource_id(account_id)
        page = _service(request).list_pending(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            limit=limit,
            cursor=cursor,
            account_id=account_id,
            result_effect=(
                FinancialResultEffect(result_effect)
                if result_effect is not None
                else None
            ),
            rule_status=(
                FinancialPendingRuleStatus(rule_status)
                if rule_status is not None
                else None
            ),
        )
    except (PendingMovementsRequestError, TypeError, ValueError):
        raise _invalid_request() from None
    except _PERSISTENCE_ERRORS as error:
        _raise_error(error)
    return _page_response(page)


__all__ = ["router"]
