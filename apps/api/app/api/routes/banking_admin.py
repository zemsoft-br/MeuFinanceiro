"""Authenticated administration of banking provider configuration."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from meufinanceiro_persistence import (
    ProviderConfigurationRecord,
    ProviderConfigurationState,
)
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.api.auth import AuthenticatedOperatorRequest, require_installation_admin
from app.services.banking_admin import (
    BankingAdministrationError,
    BankingAdministrationErrorCode,
    BankingAdministrationService,
)

router = APIRouter(
    prefix="/admin/banking/providers",
    tags=["banking-administration"],
)


class ConfigureProviderRequest(BaseModel):
    client_id: SecretStr = Field(min_length=1, max_length=16_384)
    client_secret: SecretStr = Field(min_length=1, max_length=16_384)

    model_config = ConfigDict(extra="forbid")


class ReplaceProviderCredentialsRequest(ConfigureProviderRequest):
    expected_revision: int = Field(ge=1)


class SetProviderStateRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    state: ProviderConfigurationState

    model_config = ConfigDict(extra="forbid")


class ProviderConfigurationResponse(BaseModel):
    configuration_id: UUID
    provider: str
    state: ProviderConfigurationState
    configuration_revision: int
    created_at: datetime
    updated_at: datetime
    enabled_at: datetime | None
    disabled_at: datetime | None


def _response(record: ProviderConfigurationRecord) -> ProviderConfigurationResponse:
    return ProviderConfigurationResponse(
        configuration_id=record.id,
        provider=record.provider,
        state=record.state,
        configuration_revision=record.configuration_revision,
        created_at=record.created_at,
        updated_at=record.updated_at,
        enabled_at=record.enabled_at,
        disabled_at=record.disabled_at,
    )


def _raise_administration_error(error: BankingAdministrationError) -> NoReturn:
    if error.code in {
        BankingAdministrationErrorCode.PROVIDER_UNAVAILABLE,
        BankingAdministrationErrorCode.CONFIGURATION_NOT_FOUND,
    }:
        status_code = status.HTTP_404_NOT_FOUND
    elif error.code in {
        BankingAdministrationErrorCode.FEATURE_DISABLED,
        BankingAdministrationErrorCode.CONFIGURATION_CONFLICT,
    }:
        status_code = status.HTTP_409_CONFLICT
    else:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    raise HTTPException(status_code=status_code, detail=str(error)) from None


def _service(request: Request) -> BankingAdministrationService:
    return cast(BankingAdministrationService, request.app.state.banking_administration)


@router.post(
    "/{provider}/configuration",
    response_model=ProviderConfigurationResponse,
    status_code=status.HTTP_201_CREATED,
)
def configure_provider(
    provider: str,
    payload: ConfigureProviderRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(require_installation_admin),
    ],
) -> ProviderConfigurationResponse:
    try:
        record = _service(request).configure_provider(
            installation_id=authenticated.principal.installation_id,
            provider=provider,
            client_id=payload.client_id.get_secret_value(),
            client_secret=payload.client_secret.get_secret_value(),
        )
    except BankingAdministrationError as error:
        _raise_administration_error(error)
    return _response(record)


@router.get(
    "/{provider}/configuration",
    response_model=ProviderConfigurationResponse,
)
def get_provider_configuration(
    provider: str,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(require_installation_admin),
    ],
) -> ProviderConfigurationResponse:
    try:
        record = _service(request).get_provider_configuration(
            installation_id=authenticated.principal.installation_id,
            provider=provider,
        )
    except BankingAdministrationError as error:
        _raise_administration_error(error)
    return _response(record)


@router.put(
    "/{provider}/credentials",
    response_model=ProviderConfigurationResponse,
)
def replace_provider_credentials(
    provider: str,
    payload: ReplaceProviderCredentialsRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(require_installation_admin),
    ],
) -> ProviderConfigurationResponse:
    try:
        record = _service(request).replace_provider_credentials(
            installation_id=authenticated.principal.installation_id,
            provider=provider,
            expected_revision=payload.expected_revision,
            client_id=payload.client_id.get_secret_value(),
            client_secret=payload.client_secret.get_secret_value(),
        )
    except BankingAdministrationError as error:
        _raise_administration_error(error)
    return _response(record)


@router.patch(
    "/{provider}/state",
    response_model=ProviderConfigurationResponse,
)
def set_provider_state(
    provider: str,
    payload: SetProviderStateRequest,
    request: Request,
    authenticated: Annotated[
        AuthenticatedOperatorRequest,
        Depends(require_installation_admin),
    ],
) -> ProviderConfigurationResponse:
    try:
        record = _service(request).set_provider_state(
            installation_id=authenticated.principal.installation_id,
            provider=provider,
            expected_revision=payload.expected_revision,
            state=payload.state,
        )
    except BankingAdministrationError as error:
        _raise_administration_error(error)
    return _response(record)
