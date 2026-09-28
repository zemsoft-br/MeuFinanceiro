"""Authenticated provider-neutral financial account and Movement routes."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from meufinanceiro_finance import (
    FinancialAccountBalanceSnapshot,
    FinancialAccountDraft,
    FinancialAccountRecord,
    FinancialAccountStatement,
    FinancialAccountType,
    FinancialLedgerStateError,
    FinancialManualEntryDraft,
    FinancialManualEntryType,
    FinancialMovementRecord,
    FinancialMovementReversalDraft,
    FinancialOpeningBalanceDraft,
    FinancialOpeningBalanceRecord,
    FinancialStatementEntry,
    FinancialTransferDraft,
    FinancialTransferRecord,
    FinancialTransferReversalDraft,
    FinancialVisibilityScope,
    Money,
    validate_financial_idempotency_key,
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
    FinancialMovementAlreadyReversedError,
    FinancialMovementBeforeOpeningBalanceError,
    FinancialMovementIdempotencyConflictError,
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
from meufinanceiro_persistence.financial_transfer_store import (
    FinancialTransferAccessError,
    FinancialTransferAccountNotFoundError,
    FinancialTransferAlreadyReversedError,
    FinancialTransferBeforeOpeningBalanceError,
    FinancialTransferIdempotencyConflictError,
    FinancialTransferNotFoundError,
    FinancialTransferPersistenceError,
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
    account_type: str = Field(
        alias="accountType", strict=True, min_length=1, max_length=32
    )
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


class FinancialManualEntryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    idempotency_key: UUID = Field(alias="idempotencyKey")
    amount: str = Field(strict=True, min_length=1, max_length=32)
    currency: str = Field(strict=True, min_length=3, max_length=3)
    effective_date: str = Field(
        alias="effectiveDate", strict=True, min_length=10, max_length=10
    )
    competence_date: str = Field(
        alias="competenceDate", strict=True, min_length=10, max_length=10
    )
    description: str = Field(strict=True, min_length=1, max_length=256)


class FinancialMovementReversalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    idempotency_key: UUID = Field(alias="idempotencyKey")
    effective_date: str = Field(
        alias="effectiveDate", strict=True, min_length=10, max_length=10
    )
    competence_date: str = Field(
        alias="competenceDate", strict=True, min_length=10, max_length=10
    )
    reason: str = Field(strict=True, min_length=1, max_length=256)


class FinancialTransferCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    idempotency_key: UUID = Field(alias="idempotencyKey")
    source_account_id: UUID = Field(alias="sourceAccountId")
    destination_account_id: UUID = Field(alias="destinationAccountId")
    amount: str = Field(strict=True, min_length=1, max_length=32)
    currency: str = Field(strict=True, min_length=3, max_length=3)
    effective_date: str = Field(
        alias="effectiveDate", strict=True, min_length=10, max_length=10
    )
    competence_date: str = Field(
        alias="competenceDate", strict=True, min_length=10, max_length=10
    )
    description: str = Field(strict=True, min_length=1, max_length=256)


class FinancialTransferReversalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    idempotency_key: UUID = Field(alias="idempotencyKey")
    effective_date: str = Field(
        alias="effectiveDate", strict=True, min_length=10, max_length=10
    )
    competence_date: str = Field(
        alias="competenceDate", strict=True, min_length=10, max_length=10
    )
    reason: str = Field(strict=True, min_length=1, max_length=256)


class FinancialTransferResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    transfer_id: UUID = Field(serialization_alias="transferId")
    source_account_id: UUID = Field(serialization_alias="sourceAccountId")
    destination_account_id: UUID = Field(serialization_alias="destinationAccountId")
    currency: str
    source_movement_id: UUID = Field(serialization_alias="sourceMovementId")
    destination_movement_id: UUID = Field(serialization_alias="destinationMovementId")
    role: str
    reversal_of_id: UUID | None = Field(serialization_alias="reversalOfId")
    created_at: datetime = Field(serialization_alias="createdAt")


class FinancialTransfersResponse(BaseModel):
    transfers: tuple[FinancialTransferResponse, ...]


class FinancialBalanceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    account_id: UUID = Field(serialization_alias="accountId")
    currency: str
    opening_balance: FinancialMoneyResponse | None = Field(
        serialization_alias="openingBalance"
    )
    movement_net: FinancialMoneyResponse = Field(serialization_alias="movementNet")
    current_balance: FinancialMoneyResponse = Field(
        serialization_alias="currentBalance"
    )
    movement_count: int = Field(serialization_alias="movementCount")
    calculated_at: datetime = Field(serialization_alias="calculatedAt")


class FinancialStatementEntryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    movement: FinancialMovementResponse
    balance_after: FinancialMoneyResponse = Field(serialization_alias="balanceAfter")


class FinancialStatementResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    account_id: UUID = Field(serialization_alias="accountId")
    currency: str
    opening_balance: FinancialMoneyResponse | None = Field(
        serialization_alias="openingBalance"
    )
    entries: tuple[FinancialStatementEntryResponse, ...]
    closing_balance: FinancialMoneyResponse = Field(
        serialization_alias="closingBalance"
    )
    calculated_at: datetime = Field(serialization_alias="calculatedAt")


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


def _idempotency_key(value: UUID) -> UUID:
    try:
        return validate_financial_idempotency_key(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid financial operation request",
        ) from None


def _positive_money(amount: str, currency: str) -> Money:
    if not _DECIMAL_PATTERN.fullmatch(amount):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid financial operation request",
        )
    try:
        parsed = Decimal(amount)
        if not parsed.is_finite() or parsed <= 0:
            raise InvalidOperation
        return Money(parsed, currency)
    except (InvalidOperation, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid financial operation request",
        ) from None


def _plain_date(value: str) -> date:
    if not _DATE_PATTERN.fullmatch(value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid financial operation request",
        )
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid financial operation request",
        ) from None


def _manual_entry_draft(
    account_id: UUID,
    payload: FinancialManualEntryCreateRequest,
    entry_type: FinancialManualEntryType,
) -> FinancialManualEntryDraft:
    try:
        return FinancialManualEntryDraft(
            account_id=account_id,
            magnitude=_positive_money(payload.amount, payload.currency),
            entry_type=entry_type,
            effective_date=_plain_date(payload.effective_date),
            competence_date=_plain_date(payload.competence_date),
            description=payload.description,
        )
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid financial operation request",
        ) from None


def _movement_reversal_draft(
    movement_id: UUID,
    payload: FinancialMovementReversalRequest,
) -> FinancialMovementReversalDraft:
    try:
        return FinancialMovementReversalDraft(
            movement_id=movement_id,
            effective_date=_plain_date(payload.effective_date),
            competence_date=_plain_date(payload.competence_date),
            reason=payload.reason,
        )
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid financial operation request",
        ) from None


def _transfer_draft(payload: FinancialTransferCreateRequest) -> FinancialTransferDraft:
    try:
        return FinancialTransferDraft(
            source_account_id=_operation_resource_id(payload.source_account_id),
            destination_account_id=_operation_resource_id(
                payload.destination_account_id
            ),
            magnitude=_positive_money(payload.amount, payload.currency),
            effective_date=_plain_date(payload.effective_date),
            competence_date=_plain_date(payload.competence_date),
            description=payload.description,
        )
    except HTTPException:
        raise
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid financial operation request",
        ) from None


def _transfer_reversal_draft(
    transfer_id: UUID,
    payload: FinancialTransferReversalRequest,
) -> FinancialTransferReversalDraft:
    try:
        return FinancialTransferReversalDraft(
            transfer_id=transfer_id,
            effective_date=_plain_date(payload.effective_date),
            competence_date=_plain_date(payload.competence_date),
            reason=payload.reason,
        )
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid financial operation request",
        ) from None


def _operation_resource_id(value: UUID) -> UUID:
    try:
        return validate_financial_resource_id(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid financial operation request",
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


def _transfer_response(record: FinancialTransferRecord) -> FinancialTransferResponse:
    return FinancialTransferResponse(
        transfer_id=record.id,
        source_account_id=record.source_account_id,
        destination_account_id=record.destination_account_id,
        currency=record.currency,
        source_movement_id=record.source_movement_id,
        destination_movement_id=record.destination_movement_id,
        role=record.role.value,
        reversal_of_id=record.reversal_of_id,
        created_at=record.created_at,
    )


def _balance_response(
    snapshot: FinancialAccountBalanceSnapshot,
) -> FinancialBalanceResponse:
    return FinancialBalanceResponse(
        account_id=snapshot.account_id,
        currency=snapshot.currency,
        opening_balance=(
            None
            if snapshot.opening_balance is None
            else _money_response(snapshot.opening_balance)
        ),
        movement_net=_money_response(snapshot.movement_net),
        current_balance=_money_response(snapshot.current_balance),
        movement_count=snapshot.movement_count,
        calculated_at=snapshot.calculated_at,
    )


def _statement_entry_response(
    entry: FinancialStatementEntry,
) -> FinancialStatementEntryResponse:
    return FinancialStatementEntryResponse(
        movement=_movement_response(entry.movement),
        balance_after=_money_response(entry.balance_after),
    )


def _statement_response(
    statement: FinancialAccountStatement,
) -> FinancialStatementResponse:
    return FinancialStatementResponse(
        account_id=statement.account_id,
        currency=statement.currency,
        opening_balance=(
            None
            if statement.opening_balance is None
            else _money_response(statement.opening_balance)
        ),
        entries=tuple(_statement_entry_response(item) for item in statement.entries),
        closing_balance=_money_response(statement.closing_balance),
        calculated_at=statement.calculated_at,
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
    if isinstance(
        error,
        (
            FinancialMovementAlreadyReversedError,
            FinancialMovementIdempotencyConflictError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="financial operation conflicts with canonical state",
        ) from None
    if isinstance(error, FinancialMovementBeforeOpeningBalanceError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="financial operation precedes opening balance",
        ) from None
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="financial service is unavailable",
    ) from None


def _raise_transfer_error(error: FinancialTransferPersistenceError) -> NoReturn:
    if isinstance(
        error,
        (FinancialTransferNotFoundError, FinancialTransferAccountNotFoundError),
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="financial resource was not found",
        ) from None
    if isinstance(error, FinancialTransferAccessError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="financial access denied",
        ) from None
    if isinstance(
        error,
        (
            FinancialTransferAlreadyReversedError,
            FinancialTransferIdempotencyConflictError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="financial operation conflicts with canonical state",
        ) from None
    if isinstance(error, FinancialTransferBeforeOpeningBalanceError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="financial operation precedes opening balance",
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
    return FinancialAccountsResponse(
        accounts=tuple(_account_response(item) for item in records)
    )


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


@router.post(
    "/accounts/{account_id}/income",
    response_model=FinancialMovementResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_income(
    account_id: UUID,
    payload: FinancialManualEntryCreateRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(require_primary_residence),
    ],
) -> FinancialMovementResponse:
    _reject_query_params(request)
    account_id = _validated_resource_id(account_id)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        record = _service(request).record_manual_entry(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=_idempotency_key(payload.idempotency_key),
            draft=_manual_entry_draft(
                account_id,
                payload,
                FinancialManualEntryType.INCOME,
            ),
        )
    except FinancialMovementPersistenceError as error:
        _raise_movement_error(error)
    return _movement_response(record)


@router.post(
    "/accounts/{account_id}/expense",
    response_model=FinancialMovementResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_expense(
    account_id: UUID,
    payload: FinancialManualEntryCreateRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(require_primary_residence),
    ],
) -> FinancialMovementResponse:
    _reject_query_params(request)
    account_id = _validated_resource_id(account_id)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        record = _service(request).record_manual_entry(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=_idempotency_key(payload.idempotency_key),
            draft=_manual_entry_draft(
                account_id,
                payload,
                FinancialManualEntryType.EXPENSE,
            ),
        )
    except FinancialMovementPersistenceError as error:
        _raise_movement_error(error)
    return _movement_response(record)


@router.post(
    "/movements/{movement_id}/reversal",
    response_model=FinancialMovementResponse,
    status_code=status.HTTP_201_CREATED,
)
def reverse_movement(
    movement_id: UUID,
    payload: FinancialMovementReversalRequest,
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
        record = _service(request).reverse_movement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=_idempotency_key(payload.idempotency_key),
            draft=_movement_reversal_draft(movement_id, payload),
        )
    except FinancialMovementPersistenceError as error:
        _raise_movement_error(error)
    return _movement_response(record)


@router.get(
    "/accounts/{account_id}/transfers",
    response_model=FinancialTransfersResponse,
)
def list_transfers(
    account_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(require_primary_residence),
    ],
) -> FinancialTransfersResponse:
    _reject_query_params(request)
    account_id = _validated_resource_id(account_id)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        records = _service(request).list_transfers(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )
    except FinancialTransferPersistenceError as error:
        _raise_transfer_error(error)
    return FinancialTransfersResponse(
        transfers=tuple(_transfer_response(record) for record in records)
    )


@router.post(
    "/transfers",
    response_model=FinancialTransferResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_transfer(
    payload: FinancialTransferCreateRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(require_primary_residence),
    ],
) -> FinancialTransferResponse:
    _reject_query_params(request)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        record = _service(request).create_transfer(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=_idempotency_key(payload.idempotency_key),
            draft=_transfer_draft(payload),
        )
    except FinancialTransferPersistenceError as error:
        _raise_transfer_error(error)
    return _transfer_response(record)


@router.post(
    "/transfers/{transfer_id}/reversal",
    response_model=FinancialTransferResponse,
    status_code=status.HTTP_201_CREATED,
)
def reverse_transfer(
    transfer_id: UUID,
    payload: FinancialTransferReversalRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(require_primary_residence),
    ],
) -> FinancialTransferResponse:
    _reject_query_params(request)
    transfer_id = _validated_resource_id(transfer_id)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        record = _service(request).reverse_transfer(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=_idempotency_key(payload.idempotency_key),
            draft=_transfer_reversal_draft(transfer_id, payload),
        )
    except FinancialTransferPersistenceError as error:
        _raise_transfer_error(error)
    return _transfer_response(record)


@router.get(
    "/accounts/{account_id}/balance",
    response_model=FinancialBalanceResponse,
)
def get_balance(
    account_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(require_primary_residence),
    ],
) -> FinancialBalanceResponse:
    _reject_query_params(request)
    account_id = _validated_resource_id(account_id)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        snapshot = _service(request).get_balance_snapshot(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )
    except FinancialAccountPersistenceError as error:
        _raise_account_error(error)
    except FinancialOpeningBalancePersistenceError as error:
        _raise_opening_balance_error(error)
    except FinancialMovementPersistenceError as error:
        _raise_movement_error(error)
    except FinancialLedgerStateError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="financial service is unavailable",
        ) from None
    return _balance_response(snapshot)


@router.get(
    "/accounts/{account_id}/statement",
    response_model=FinancialStatementResponse,
)
def get_statement(
    account_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(require_primary_residence),
    ],
) -> FinancialStatementResponse:
    _reject_query_params(request)
    account_id = _validated_resource_id(account_id)
    installation_id, residence_id, operator_id = _context(authenticated)
    try:
        statement = _service(request).get_statement(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            account_id=account_id,
        )
    except FinancialAccountPersistenceError as error:
        _raise_account_error(error)
    except FinancialOpeningBalancePersistenceError as error:
        _raise_opening_balance_error(error)
    except FinancialMovementPersistenceError as error:
        _raise_movement_error(error)
    except FinancialLedgerStateError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="financial service is unavailable",
        ) from None
    return _statement_response(statement)


__all__ = ["router"]
