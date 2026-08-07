"""Authenticated residence-scoped Pluggy connection bootstrap."""

from __future__ import annotations

from typing import Annotated, NoReturn, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from meufinanceiro_banking_pluggy_execution import (
    PluggyConnectTokenError,
    PluggyConnectTokenErrorCode,
    PluggyConnectTokenService,
)
from pydantic import BaseModel, Field

from app.api.auth import (
    AuthenticatedOperatorRequest,
    require_installation_admin_primary_residence,
)

router = APIRouter(
    prefix="/banking/pluggy",
    tags=["banking-connections"],
)


class PluggyConnectTokenResponse(BaseModel):
    access_token: str = Field(
        min_length=1,
        max_length=4096,
        serialization_alias="accessToken",
    )


async def _require_connect_token_request(
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
    if await request.body():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="request body is not allowed",
        )
    return authenticated


def _service(request: Request) -> PluggyConnectTokenService:
    service = getattr(request.app.state, "banking_pluggy_connect_token", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="banking provider is unavailable",
        )
    return cast(PluggyConnectTokenService, service)


def _raise_connect_token_error(error: PluggyConnectTokenError) -> NoReturn:
    if error.code in {
        PluggyConnectTokenErrorCode.CONFIGURATION_REQUIRED,
        PluggyConnectTokenErrorCode.PROVIDER_NOT_ENABLED,
    }:
        status_code = status.HTTP_409_CONFLICT
    elif error.code is PluggyConnectTokenErrorCode.TEMPORARILY_UNAVAILABLE:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif error.code in {
        PluggyConnectTokenErrorCode.INVALID_PROVIDER_RESPONSE,
        PluggyConnectTokenErrorCode.PROVIDER_REJECTED,
    }:
        status_code = status.HTTP_502_BAD_GATEWAY
    else:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    raise HTTPException(status_code=status_code, detail=str(error)) from None


@router.post(
    "/connect-token",
    response_model=PluggyConnectTokenResponse,
)
def issue_connect_token(
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(_require_connect_token_request),
    ],
) -> PluggyConnectTokenResponse:
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
        )
    except PluggyConnectTokenError as error:
        _raise_connect_token_error(error)
    return PluggyConnectTokenResponse(access_token=issued.access_token)
