from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from meufinanceiro_banking import BankingProviderRegistry
from meufinanceiro_persistence import BankingIntegrationStore
from meufinanceiro_security.envelope import SecretCipher
from meufinanceiro_security.keyring import load_keyring
from meufinanceiro_security.redaction import install_log_redaction

from app.api.routes.demo import router as demo_router
from app.api.routes.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.database import create_database
from app.services.banking_admin import BankingAdministrationService


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
        app.state.secret_cipher = secret_cipher
        app.state.database = database
        app.state.settings = resolved_settings
        app.state.banking_provider_registry = provider_registry
        app.state.banking_administration = BankingAdministrationService(
            banking_store,
            provider_registry,
            feature_enabled=resolved_settings.app_banking_enabled,
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
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(demo_router, prefix="/api/v1")
    return application


app = create_app()
