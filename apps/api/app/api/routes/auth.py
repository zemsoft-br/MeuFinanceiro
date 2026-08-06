"""Local operator session endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from meufinanceiro_persistence import OperatorRole, OperatorSessionPrincipal
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.api.auth import AuthenticatedOperatorRequest, require_operator_session
from app.services.operator_auth import (
    InvalidOperatorCredentialsError,
    OperatorAuthenticationService,
    OperatorAuthenticationUnavailableError,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


class SessionLoginRequest(BaseModel):
    login: str = Field(min_length=3, max_length=64)
    password: SecretStr

    model_config = ConfigDict(extra="forbid")


class OperatorPrincipalResponse(BaseModel):
    operator_id: UUID
    installation_id: UUID
    primary_residence_id: UUID | None
    login: str
    role: OperatorRole
    expires_at: datetime


class SessionLoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    operator: OperatorPrincipalResponse


def _principal_response(
    principal: OperatorSessionPrincipal,
) -> OperatorPrincipalResponse:
    return OperatorPrincipalResponse(
        operator_id=principal.operator_id,
        installation_id=principal.installation_id,
        primary_residence_id=principal.primary_residence_id,
        login=principal.login_name,
        role=principal.role,
        expires_at=principal.expires_at,
    )


@router.post("/session", response_model=SessionLoginResponse)
def create_session(
    payload: SessionLoginRequest,
    request: Request,
) -> SessionLoginResponse:
    service: OperatorAuthenticationService = request.app.state.operator_authentication
    try:
        issued = service.login(
            login_name=payload.login,
            password=payload.password.get_secret_value(),
        )
    except InvalidOperatorCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="operator credentials are invalid",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except OperatorAuthenticationUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator authentication is unavailable",
        ) from None
    return SessionLoginResponse(
        access_token=issued.token,
        expires_at=issued.principal.expires_at,
        operator=_principal_response(issued.principal),
    )


@router.get("/session", response_model=OperatorPrincipalResponse)
def get_session(
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(require_operator_session),
    ],
) -> OperatorPrincipalResponse:
    return _principal_response(authenticated.principal)


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(require_operator_session),
    ],
    request: Request,
) -> Response:
    service: OperatorAuthenticationService = request.app.state.operator_authentication
    try:
        service.logout(authenticated.token)
    except OperatorAuthenticationUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator authentication is unavailable",
        ) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
