"""Authenticated Pluggy update-mode token issuance for one local connection."""

from __future__ import annotations

from typing import Annotated, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from meufinanceiro_banking_pluggy_execution import (
    PluggyReauthenticationError,
    PluggyReauthenticationErrorCode,
    PluggyReauthenticationTokenService,
)
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import (
    AuthenticatedOperatorRequest,
    require_installation_admin_primary_residence,
)

router = APIRouter(
    prefix="/banking/pluggy",
    tags=["banking-connections"],
)


class PluggyReauthenticationTokenResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    access_token: str = Field(
        min_length=1,
        max_length=4096,
        serialization_alias="accessToken",
    )
    item_id: str = Field(
        min_length=1,
        max_length=512,
        serialization_alias="itemId",
    )


async def _require_reauthentication_request(
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
    async for chunk in request.stream():
        if chunk:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="request body is not allowed",
            )
    return authenticated


def _service(request: Request) -> PluggyReauthenticationTokenService:
    service = getattr(request.app.state, "banking_pluggy_reauthentication", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="banking provider is unavailable",
        )
    return cast(PluggyReauthenticationTokenService, service)


def _raise_reauthentication_error(error: PluggyReauthenticationError) -> NoReturn:
    if error.code in {
        PluggyReauthenticationErrorCode.CONNECTION_NOT_AVAILABLE,
        PluggyReauthenticationErrorCode.CONFIGURATION_REQUIRED,
        PluggyReauthenticationErrorCode.PROVIDER_NOT_ENABLED,
    }:
        status_code = status.HTTP_409_CONFLICT
    elif error.code is PluggyReauthenticationErrorCode.CONNECTION_NOT_ALLOWED:
        status_code = status.HTTP_403_FORBIDDEN
    elif error.code in {
        PluggyReauthenticationErrorCode.CONNECTION_NOT_FOUND,
        PluggyReauthenticationErrorCode.ITEM_UNAVAILABLE,
    }:
        status_code = status.HTTP_404_NOT_FOUND
    elif error.code in {
        PluggyReauthenticationErrorCode.INVALID_PROVIDER_RESPONSE,
        PluggyReauthenticationErrorCode.PROVIDER_REJECTED,
    }:
        status_code = status.HTTP_502_BAD_GATEWAY
    else:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    raise HTTPException(status_code=status_code, detail=str(error)) from None


@router.post(
    "/connections/{connection_id}/reauthentication-token",
    response_model=PluggyReauthenticationTokenResponse,
)
def issue_reauthentication_token(
    connection_id: UUID,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(_require_reauthentication_request),
    ],
) -> PluggyReauthenticationTokenResponse:
    residence_id = authenticated.principal.primary_residence_id
    if residence_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="primary residence is required",
        )
    try:
        issued = _service(request).issue(
            installation_id=authenticated.principal.installation_id,
            residence_id=residence_id,
            connection_id=connection_id,
        )
    except PluggyReauthenticationError as error:
        _raise_reauthentication_error(error)
    return PluggyReauthenticationTokenResponse(
        access_token=issued.access_token,
        item_id=issued.item_id,
    )
