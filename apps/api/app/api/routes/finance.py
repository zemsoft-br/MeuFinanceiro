"""Authenticated provider-neutral financial account and Movement routes."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from meufinanceiro_finance import (
    FinancialAccountDraft,
    FinancialAccountRecord,
    FinancialAccountType,
    FinancialMovementRecord,
    FinancialOpeningBalanceDraft,
    FinancialOpeningBalanceRecord,
    FinancialVisibilityScope,
    Money,
    validate_financial_resource_id,
)
from meufinanceiro_persistence.financial_account_store import (
    FinancialAccountAccessError,
    FinancialAccountNotFoundError,
    FinancialAccountPersistenceError,
)
from meufinanceiro_persistence.financial_movement_store import (
    FinancialMovementAccessError,
    FinancialMovementAccountNotFoundError,
    FinancialMovementNotFoundError,
    FinancialMovementPersistenceError,
)
from meufinanceiro_persistence.financial_opening_balance_store import (
    FinancialOpeningBalanceAccessError,
    FinancialOpeningBalanceAccountNotFoundError,
    FinancialOpeningBalanceAlreadyExistsError,
    FinancialOpeningBalanceCurrencyMismatchError,
    FinancialOpeningBalancePersistenceError,
)
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import AuthenticatedOperatorRequest, require_primary_residence
from app.services.financial_core import FinancialCoreService

router = APIRouter(prefix="/finance", tags=["finance"])

_DECIMAL_PATTERN = re.compile(r"^-?(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,8})?$")
_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class FinancialMoneyResponse(BaseModel):
    amount: str
    currency: str


class FinancialAccountCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(strict=True, min_length=1, max_length=96)
    account_type: str = Field(alias="accountType", strict=True, min_length=1, max_length=32)
    custom_type_name: str | None = Field(
        default=None,
        alias="customTypeName",
        strict=True,
        max_length=96,
    )
    currency: str = Field(strict=True, min_length=3, max_length=3)
    visibility_scope: str = Field(
        alias="visibilityScope",
        strict=True,
        min_length=1,
        max_length=16,
    )


class FinancialAccountResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    account_id: UUID = Field(serialization_alias="accountId")
    owner_operator_id: UUID = Field(serialization_alias="ownerOperatorId")
    visibility_scope: str = Field(serialization_alias="visibilityScope")
    account_type: str = Field(serialization_alias="accountType")
    custom_type_name: str | None = Field(serialization_alias="customTypeName")
    name: str
    currency: str
    status: str
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")
    archived_at: datetime | None = Field(serialization_alias="archivedAt")


class FinancialAccountsResponse(BaseModel):
    accounts: tuple[FinancialAccountResponse, ...]


class FinancialOpeningBalanceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    amount: str = Field(strict=True, min_length=1, max_length=32)
    currency: str = Field(strict=True, min_length=3, max_length=3)
    effective_date: str = Field(
        alias="effectiveDate",
        strict=True,
        min_length=10,
        max_length=10,
    )


class FinancialOpeningBalanceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    opening_balance_id: UUID = Field(serialization_alias="openingBalanceId")
    account_id: UUID = Field(serialization_alias="accountId")
    money: FinancialMoneyResponse
    effective_date: date = Field(serialization_alias="effectiveDate")
    created_at: datetime = Field(serialization_alias="createdAt")


class FinancialOpeningBalanceEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    opening_balance: FinancialOpeningBalanceResponse | None = Field(
        serialization_alias="openingBalance"
    )


class FinancialMovementResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    movement_id: UUID = Field(serialization_alias="movementId")
    account_id: UUID = Field(serialization_alias="accountId")
    money: FinancialMoneyResponse
    result_effect: str = Field(serialization_alias="resultEffect")
    role: str
    effective_date: date = Field(serialization_alias="effectiveDate")
    competence_date: date = Field(serialization_alias="competenceDate")
    description: str | None
    reversal_of_id: UUID | None = Field(serialization_alias="reversalOfId")
    reversal_reason: str | None = Field(serialization_alias="reversalReason")
    created_at: datetime = Field(serialization_alias="createdAt")


class FinancialMovementsResponse(BaseModel):
    movements: tuple[FinancialMovementResponse, ...]


def _service(request: Request) -> FinancialCoreService:
    service = getattr(request.app.state, "financial_core", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="financial service is unavailable",
        )
    return cast(FinancialCoreService, service)


def _context(
    authenticated: AuthenticatedOperatorRequest,
) -> tuple[UUID, UUID, UUID]:
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


def _account_draft(payload: FinancialAccountCreateRequest) -> FinancialAccountDraft:
    try:
        return FinancialAccountDraft(
            name=payload.name,
            currency=payload.currency,
            account_type=FinancialAccountType(payload.account_type),
            visibility_scope=FinancialVisibilityScope(payload.visibility_scope),
            custom_type_name=payload.custom_type_name,
        )
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid financial account request",
        ) from None


def _opening_balance_draft(
    payload: FinancialOpeningBalanceCreateRequest,
) -> FinancialOpeningBalanceDraft:
    if not _DECIMAL_PATTERN.fullmatch(payload.amount):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid financial opening balance request",
        )
    if not _DATE_PATTERN.fullmatch(payload.effective_date):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid financial opening balance request",
        )
    try:
        amount = Decimal(payload.amount)
        if not amount.is_finite():
            raise InvalidOperation
        effective_date = date.fromisoformat(payload.effective_date)
        return FinancialOpeningBalanceDraft(
            amount=Money(amount, payload.currency),
            effective_date=effective_date,
        )
    except (InvalidOperation, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid financial opening balance request",
        ) from None


def _validated_resource_id(value: UUID) -> UUID:
    try:
        return validate_financial_resource_id(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="financial resource was not found",
        ) from None


def _money_response(money: Money) -> FinancialMoneyResponse:
    return FinancialMoneyResponse(
        amount=money.canonical_amount,
        currency=money.currency,
    )


def _account_response(record: FinancialAccountRecord) -> FinancialAccountResponse:
    return FinancialAccountResponse(
        account_id=record.id,
        owner_operator_id=record.owner_operator_id,
        visibility_scope=record.visibility_scope.value,
        account_type=record.account_type.value,
        custom_type_name=record.custom_type_name,
        name=record.name,
        currency=record.currency,
        status=record.status.value,
        created_at=record.created_at,
        updated_at=record.updated_at,
        archived_at=record.archived_at,
    )


def _opening_balance_response(
    record: FinancialOpeningBalanceRecord,
) -> FinancialOpeningBalanceResponse:
    return FinancialOpeningBalanceResponse(
        opening_balance_id=record.id,
        account_id=record.account_id,
        money=_money_response(record.amount),
        effective_date=record.effective_date,
        created_at=record.created_at,
    )


def _movement_response(record: FinancialMovementRecord) -> FinancialMovementResponse:
    return FinancialMovementResponse(
        movement_id=record.id,
        account_id=record.account_id,
        money=_money_response(record.amount),
        result_effect=record.result_effect.value,
        role=record.role.value,
        effective_date=record.effective_date,
        competence_date=record.competence_date,
        description=record.description,
        reversal_of_id=record.reversal_of_id,
        reversal_reason=record.reversal_reason,
        created_at=record.created_at,
    )


def _raise_account_error(error: FinancialAccountPersistenceError) -> NoReturn:
    if isinstance(error, FinancialAccountNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="financial account was not found",
        ) from None
    if isinstance(error, FinancialAccountAccessError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="financial access denied",
        ) from None
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="financial service is unavailable",
    ) from None


def _raise_opening_balance_error(
    error: FinancialOpeningBalancePersistenceError,
) -> NoReturn:
    if isinstance(error, FinancialOpeningBalanceAlreadyExistsError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="financial account already has an opening balance",
        ) from None
    if isinstance(error, FinancialOpeningBalanceAccountNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="financial account was not found",
        ) from None
    if isinstance(error, FinancialOpeningBalanceCurrencyMismatchError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid financial opening balance request",
        ) from None
    if isinstance(error, FinancialOpeningBalanceAccessError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="financial access denied",
        ) from None
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="financial service is unavailable",
    ) from None


def _raise_movement_error(error: FinancialMovementPersistenceError) -> NoReturn:
    if isinstance(
        error,
        (FinancialMovementNotFoundError, FinancialMovementAccountNotFoundError),
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="financial resource was not found",
        ) from None
    if isinstance(error, FinancialMovementAccessError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="financial access denied",
        ) from None
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="financial service is unavailable",
    ) from None


@router.get("/accounts", response_model=FinancialAccountsResponse)
def list_accounts(
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(require_primary_residence),
    ],
) -> FinancialAccountsResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        records = _service(request).list_accounts(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
        )
    except FinancialAccountPersistenceError as error:
        _raise_account_error(error)
    return FinancialAccountsResponse(accounts=tuple(_account_response(item) for item in records))


@router.post(
    "/accounts",
    response_model=FinancialAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_account(
    payload: FinancialAccountCreateRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(require_primary_residence),
    ],
) -> FinancialAccountResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        record = _service(request).create_account(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            draft=_account_draft(payload),
        )
    except FinancialAccountPersistenceError as error:
        _raise_account_error(error)
    return _account_response(record)


@router.get("/accounts/{account_id}", response_model=FinancialAccountResponse)
def get_account(
    account_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(require_primary_residence),
    ],
) -> FinancialAccountResponse:
    _reject_query_params(request)
    account_id = _validated_resource_id(account_id)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        record = _service(request).get_account(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )
    except FinancialAccountPersistenceError as error:
        _raise_account_error(error)
    return _account_response(record)


@router.get(
    "/accounts/{account_id}/opening-balance",
    response_model=FinancialOpeningBalanceEnvelope,
)
def get_opening_balance(
    account_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(require_primary_residence),
    ],
) -> FinancialOpeningBalanceEnvelope:
    _reject_query_params(request)
    account_id = _validated_resource_id(account_id)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        record = _service(request).get_opening_balance(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )
    except FinancialAccountPersistenceError as error:
        _raise_account_error(error)
    except FinancialOpeningBalancePersistenceError as error:
        _raise_opening_balance_error(error)
    return FinancialOpeningBalanceEnvelope(
        opening_balance=None if record is None else _opening_balance_response(record)
    )


@router.post(
    "/accounts/{account_id}/opening-balance",
    response_model=FinancialOpeningBalanceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_opening_balance(
    account_id: UUID,
    payload: FinancialOpeningBalanceCreateRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(require_primary_residence),
    ],
) -> FinancialOpeningBalanceResponse:
    _reject_query_params(request)
    account_id = _validated_resource_id(account_id)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        record = _service(request).create_opening_balance(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
            draft=_opening_balance_draft(payload),
        )
    except FinancialOpeningBalancePersistenceError as error:
        _raise_opening_balance_error(error)
    return _opening_balance_response(record)


@router.get(
    "/accounts/{account_id}/movements",
    response_model=FinancialMovementsResponse,
)
def list_movements(
    account_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(require_primary_residence),
    ],
) -> FinancialMovementsResponse:
    _reject_query_params(request)
    account_id = _validated_resource_id(account_id)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        records = _service(request).list_movements(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )
    except FinancialMovementPersistenceError as error:
        _raise_movement_error(error)
    return FinancialMovementsResponse(
        movements=tuple(_movement_response(item) for item in records)
    )


@router.get("/movements/{movement_id}", response_model=FinancialMovementResponse)
def get_movement(
    movement_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(require_primary_residence),
    ],
) -> FinancialMovementResponse:
    _reject_query_params(request)
    movement_id = _validated_resource_id(movement_id)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        record = _service(request).get_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            movement_id=movement_id,
        )
    except FinancialMovementPersistenceError as error:
        _raise_movement_error(error)
    return _movement_response(record)


__all__ = ["router"]
