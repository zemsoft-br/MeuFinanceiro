"""Authenticated registration of a Pluggy Item completed by Connect Widget."""

from __future__ import annotations

from typing import Annotated, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from meufinanceiro_banking_pluggy_execution import (
    PluggyConnectionRegistrationError,
    PluggyConnectionRegistrationErrorCode,
    PluggyConnectionRegistrationService,
)
from meufinanceiro_persistence import StoredConnectionStatus
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import (
    AuthenticatedOperatorRequest,
    require_installation_admin_primary_residence,
)

router = APIRouter(
    prefix="/banking/pluggy",
    tags=["banking-connections"],
)


class RegisterPluggyConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(
        alias="itemId",
        min_length=1,
        max_length=512,
    )


class RegisteredPluggyConnectionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    connection_id: UUID = Field(serialization_alias="connectionId")
    status: StoredConnectionStatus
    requires_user_action: bool = Field(serialization_alias="requiresUserAction")


async def _require_registration_request(
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(require_installation_admin_primary_residence),
    ],
) -> AuthenticatedOperatorRequest:
    if request.query_params:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="query parameters are not allowed",
        )
    return authenticated


def _service(request: Request) -> PluggyConnectionRegistrationService:
    service = getattr(request.app.state, "banking_pluggy_connection_registration", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="banking provider is unavailable",
        )
    return cast(PluggyConnectionRegistrationService, service)


def _raise_registration_error(error: PluggyConnectionRegistrationError) -> NoReturn:
    if error.code in {
        PluggyConnectionRegistrationErrorCode.CONFIGURATION_REQUIRED,
        PluggyConnectionRegistrationErrorCode.PROVIDER_NOT_ENABLED,
        PluggyConnectionRegistrationErrorCode.CONNECTION_CONFLICT,
    }:
        status_code = status.HTTP_409_CONFLICT
    elif error.code is PluggyConnectionRegistrationErrorCode.ITEM_NOT_ALLOWED:
        status_code = status.HTTP_403_FORBIDDEN
    elif error.code is PluggyConnectionRegistrationErrorCode.ITEM_UNAVAILABLE:
        status_code = status.HTTP_404_NOT_FOUND
    elif error.code in {
        PluggyConnectionRegistrationErrorCode.INVALID_PROVIDER_RESPONSE,
        PluggyConnectionRegistrationErrorCode.PROVIDER_REJECTED,
    }:
        status_code = status.HTTP_502_BAD_GATEWAY
    else:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    raise HTTPException(status_code=status_code, detail=str(error)) from None


@router.post(
    "/connections",
    response_model=RegisteredPluggyConnectionResponse,
)
def register_connection(
    request: Request,
    payload: RegisterPluggyConnectionRequest,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(_require_registration_request),
    ],
) -> RegisteredPluggyConnectionResponse:
    residence_id = authenticated.principal.primary_residence_id
    if residence_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="primary residence is required",
        )
    try:
        registered = _service(request).register(
            installation_id=authenticated.principal.installation_id,
            residence_id=residence_id,
            item_id=payload.item_id,
        )
    except PluggyConnectionRegistrationError as error:
        _raise_registration_error(error)
    return RegisteredPluggyConnectionResponse(
        connection_id=registered.connection_id,
        status=registered.status,
        requires_user_action=registered.requires_user_action,
    )
