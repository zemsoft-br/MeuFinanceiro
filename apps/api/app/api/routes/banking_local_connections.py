"""Authenticated local-only banking connection metadata."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from meufinanceiro_persistence import BankingConnectionQueryError
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import (
    AuthenticatedOperatorRequest,
    require_installation_admin_primary_residence,
)
from app.services.banking_connections import BankingConnectionsService

router = APIRouter(prefix="/banking", tags=["banking-connections"])


class LocalBankingConnectionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    connection_id: UUID = Field(serialization_alias="connectionId")
    provider: str
    status: str
    requires_user_action: bool = Field(serialization_alias="requiresUserAction")
    last_successful_sync_at: datetime | None = Field(
        serialization_alias="lastSuccessfulSyncAt"
    )
    last_attempt_at: datetime | None = Field(serialization_alias="lastAttemptAt")
    next_refresh_allowed_at: datetime | None = Field(
        serialization_alias="nextRefreshAllowedAt"
    )
    consent_expires_at: datetime | None = Field(serialization_alias="consentExpiresAt")
    disconnected_at: datetime | None = Field(serialization_alias="disconnectedAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")
    reauthentication_available: bool = Field(
        serialization_alias="reauthenticationAvailable"
    )


class LocalBankingConnectionsResponse(BaseModel):
    connections: tuple[LocalBankingConnectionResponse, ...]


async def _require_local_connections_request(
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


def _service(request: Request) -> BankingConnectionsService:
    service = getattr(request.app.state, "banking_connections", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="banking connection metadata is unavailable",
        )
    return cast(BankingConnectionsService, service)


@router.get("/connections", response_model=LocalBankingConnectionsResponse)
def list_local_connections(
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(_require_local_connections_request),
    ],
) -> LocalBankingConnectionsResponse:
    residence_id = authenticated.principal.primary_residence_id
    if residence_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="primary residence is required",
        )
    try:
        connections = _service(request).list_connections(
            installation_id=authenticated.principal.installation_id,
            residence_id=residence_id,
        )
    except BankingConnectionQueryError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="banking connection metadata is unavailable",
        ) from None

    return LocalBankingConnectionsResponse(
        connections=tuple(
            LocalBankingConnectionResponse(
                connection_id=connection.connection_id,
                provider=connection.provider,
                status=connection.status.value,
                requires_user_action=connection.requires_user_action,
                last_successful_sync_at=connection.last_successful_sync_at,
                last_attempt_at=connection.last_attempt_at,
                next_refresh_allowed_at=connection.next_refresh_allowed_at,
                consent_expires_at=connection.consent_expires_at,
                disconnected_at=connection.disconnected_at,
                updated_at=connection.updated_at,
                reauthentication_available=connection.reauthentication_available,
            )
            for connection in connections
        )
    )
