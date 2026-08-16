from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from meufinanceiro_banking import BankingProviderRegistry
from meufinanceiro_banking_pluggy_execution import (
    PluggyConnectionRegistrationService,
    PluggyConnectTokenService,
    PluggyReadOnlyExecutionService,
    PluggyReauthenticationTokenService,
)
from meufinanceiro_persistence import (
    BankingConnectionQueryStore,
    BankingIntegrationStore,
    OperatorIdentityStore,
)
from meufinanceiro_persistence.financial_account_store import FinancialAccountStore
from meufinanceiro_persistence.financial_movement_store import FinancialMovementStore
from meufinanceiro_persistence.financial_opening_balance_store import (
    FinancialOpeningBalanceStore,
)
from meufinanceiro_security.envelope import SecretCipher
from meufinanceiro_security.keyring import load_keyring
from meufinanceiro_security.redaction import install_log_redaction
from starlette.responses import JSONResponse, Response

from app.api.auth import AuthenticationNoStoreMiddleware
from app.api.routes.auth import router as auth_router
from app.api.routes.banking_admin import router as banking_admin_router
from app.api.routes.banking_connect import router as banking_connect_router
from app.api.routes.banking_connections import router as banking_connections_router
from app.api.routes.banking_local_connections import (
    router as banking_local_connections_router,
)
from app.api.routes.banking_reauthentication import (
    router as banking_reauthentication_router,
)
from app.api.routes.demo import router as demo_router
from app.api.routes.finance import router as finance_router
from app.api.routes.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.database import create_database
from app.services.banking_admin import BankingAdministrationService
from app.services.banking_connections import BankingConnectionsService
from app.services.financial_core import FinancialCoreService
from app.services.operator_auth import OperatorAuthenticationService

_BANKING_VALIDATION_PREFIXES = (
    "/api/v1/admin/banking/",
    "/api/v1/banking/",
)
_FINANCE_VALIDATION_PREFIX = "/api/v1/finance/"


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        install_log_redaction()
        keyring = load_keyring(resolved_settings.app_keyring_file)
        database = create_database(resolved_settings)
        secret_cipher = SecretCipher(keyring)
        provider_registry = BankingProviderRegistry().freeze()
        banking_store = BankingIntegrationStore(database.engine, secret_cipher)
        banking_connection_query_store = BankingConnectionQueryStore(database.engine)
        operator_identity_store = OperatorIdentityStore(database.engine)
        operator_authentication = OperatorAuthenticationService(operator_identity_store)
        financial_account_store = FinancialAccountStore(database.engine)
        financial_opening_balance_store = FinancialOpeningBalanceStore(database.engine)
        financial_movement_store = FinancialMovementStore(database.engine)
        available_providers = (
            ("pluggy",) if resolved_settings.app_banking_pluggy_enabled else ()
        )
        banking_pluggy_execution: PluggyReadOnlyExecutionService | None = None
        banking_pluggy_connect_token: PluggyConnectTokenService | None = None
        banking_pluggy_connection_registration: (
            PluggyConnectionRegistrationService | None
        ) = None
        banking_pluggy_reauthentication: PluggyReauthenticationTokenService | None = (
            None
        )
        if (
            resolved_settings.app_banking_enabled
            and resolved_settings.app_banking_pluggy_enabled
        ):
            banking_pluggy_execution = PluggyReadOnlyExecutionService(banking_store)
            banking_pluggy_connect_token = PluggyConnectTokenService(banking_store)
            banking_pluggy_connection_registration = (
                PluggyConnectionRegistrationService(banking_store)
            )
            banking_pluggy_reauthentication = PluggyReauthenticationTokenService(
                banking_store
            )

        app.state.secret_cipher = secret_cipher
        app.state.database = database
        app.state.settings = resolved_settings
        app.state.banking_provider_registry = provider_registry
        app.state.banking_pluggy_execution = banking_pluggy_execution
        app.state.banking_pluggy_connect_token = banking_pluggy_connect_token
        app.state.banking_pluggy_connection_registration = (
            banking_pluggy_connection_registration
        )
        app.state.banking_pluggy_reauthentication = banking_pluggy_reauthentication
        app.state.banking_connections = BankingConnectionsService(
            banking_connection_query_store,
            pluggy_reauthentication_available=(
                banking_pluggy_reauthentication is not None
            ),
        )
        app.state.operator_identity_store = operator_identity_store
        app.state.operator_authentication = operator_authentication
        app.state.financial_core = FinancialCoreService(
            financial_account_store,
            financial_opening_balance_store,
            financial_movement_store,
        )
        app.state.banking_administration = BankingAdministrationService(
            banking_store,
            provider_registry,
            feature_enabled=resolved_settings.app_banking_enabled,
            available_providers=available_providers,
        )
        try:
            yield
        finally:
            database.dispose()

    application = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        docs_url="/api/v1/docs",
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
        lifespan=lifespan,
    )

    @application.exception_handler(RequestValidationError)
    async def sanitize_sensitive_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> Response:
        if request.url.path.startswith(_FINANCE_VALIDATION_PREFIX):
            return JSONResponse(
                status_code=422,
                content={"detail": "invalid financial request"},
            )
        if request.url.path.startswith(_BANKING_VALIDATION_PREFIXES):
            return JSONResponse(
                status_code=422,
                content={"detail": "invalid banking request"},
            )
        return await request_validation_exception_handler(request, error)

    application.add_middleware(AuthenticationNoStoreMiddleware)
    application.include_router(auth_router, prefix="/api/v1")
    application.include_router(banking_admin_router, prefix="/api/v1")
    application.include_router(banking_connect_router, prefix="/api/v1")
    application.include_router(banking_connections_router, prefix="/api/v1")
    application.include_router(
        banking_local_connections_router,
        prefix="/api/v1",
    )
    application.include_router(
        banking_reauthentication_router,
        prefix="/api/v1",
    )
    application.include_router(finance_router, prefix="/api/v1")
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(demo_router, prefix="/api/v1")
    return application


app = create_app()
