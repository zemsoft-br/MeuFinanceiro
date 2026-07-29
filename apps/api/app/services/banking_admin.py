"""Internal administration use cases for banking provider configuration."""

from __future__ import annotations

from enum import StrEnum
from typing import NoReturn, Protocol
from uuid import UUID

from meufinanceiro_banking import (
    BankingProviderRegistry,
    ProviderNotRegisteredError,
)
from meufinanceiro_persistence import (
    BankingPersistenceError,
    ConfigurationConflictError,
    ConfigurationNotFoundError,
    ProviderConfigurationRecord,
    ProviderConfigurationState,
)


class BankingAdministrationErrorCode(StrEnum):
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    FEATURE_DISABLED = "FEATURE_DISABLED"
    CONFIGURATION_NOT_FOUND = "CONFIGURATION_NOT_FOUND"
    CONFIGURATION_CONFLICT = "CONFIGURATION_CONFLICT"
    PERSISTENCE_FAILURE = "PERSISTENCE_FAILURE"


class BankingAdministrationError(RuntimeError):
    """Stable administration error that never contains credentials or ciphertext."""

    def __init__(
        self,
        code: BankingAdministrationErrorCode,
        safe_message: str,
    ) -> None:
        self.code = code
        super().__init__(safe_message)


class BankingConfigurationStore(Protocol):
    def create_configuration(
        self,
        *,
        installation_id: UUID,
        provider: str,
        client_id: str,
        client_secret: str,
    ) -> ProviderConfigurationRecord: ...

    def get_configuration(
        self,
        *,
        installation_id: UUID,
        provider: str,
    ) -> ProviderConfigurationRecord: ...

    def replace_credentials(
        self,
        *,
        installation_id: UUID,
        provider: str,
        expected_revision: int,
        client_id: str,
        client_secret: str,
    ) -> ProviderConfigurationRecord: ...

    def set_configuration_state(
        self,
        *,
        installation_id: UUID,
        provider: str,
        expected_revision: int,
        state: ProviderConfigurationState,
    ) -> ProviderConfigurationRecord: ...


class BankingAdministrationService:
    """Coordinate administrative state without performing provider I/O."""

    def __init__(
        self,
        store: BankingConfigurationStore,
        registry: BankingProviderRegistry,
        *,
        feature_enabled: bool,
    ) -> None:
        self._store = store
        self._registry = registry
        self._feature_enabled = feature_enabled

    @property
    def feature_enabled(self) -> bool:
        return self._feature_enabled

    def configure_provider(
        self,
        *,
        installation_id: UUID,
        provider: str,
        client_id: str,
        client_secret: str,
    ) -> ProviderConfigurationRecord:
        normalized_provider = self._require_registered(provider)
        try:
            return self._store.create_configuration(
                installation_id=installation_id,
                provider=normalized_provider,
                client_id=client_id,
                client_secret=client_secret,
            )
        except BankingPersistenceError as error:
            self._raise_persistence_error(error)

    def get_provider_configuration(
        self,
        *,
        installation_id: UUID,
        provider: str,
    ) -> ProviderConfigurationRecord:
        try:
            return self._store.get_configuration(
                installation_id=installation_id,
                provider=provider,
            )
        except BankingPersistenceError as error:
            self._raise_persistence_error(error)

    def replace_provider_credentials(
        self,
        *,
        installation_id: UUID,
        provider: str,
        expected_revision: int,
        client_id: str,
        client_secret: str,
    ) -> ProviderConfigurationRecord:
        normalized_provider = self._require_registered(provider)
        try:
            return self._store.replace_credentials(
                installation_id=installation_id,
                provider=normalized_provider,
                expected_revision=expected_revision,
                client_id=client_id,
                client_secret=client_secret,
            )
        except BankingPersistenceError as error:
            self._raise_persistence_error(error)

    def set_provider_state(
        self,
        *,
        installation_id: UUID,
        provider: str,
        expected_revision: int,
        state: ProviderConfigurationState,
    ) -> ProviderConfigurationRecord:
        normalized_provider = provider
        if state is ProviderConfigurationState.ENABLED:
            if not self._feature_enabled:
                raise BankingAdministrationError(
                    BankingAdministrationErrorCode.FEATURE_DISABLED,
                    "banking integration is disabled",
                )
            normalized_provider = self._require_registered(provider)
        elif state is ProviderConfigurationState.CONFIGURED:
            normalized_provider = self._require_registered(provider)

        try:
            return self._store.set_configuration_state(
                installation_id=installation_id,
                provider=normalized_provider,
                expected_revision=expected_revision,
                state=state,
            )
        except BankingPersistenceError as error:
            self._raise_persistence_error(error)

    def _require_registered(self, provider: str) -> str:
        try:
            return self._registry.require_registered(provider)
        except ProviderNotRegisteredError:
            raise BankingAdministrationError(
                BankingAdministrationErrorCode.PROVIDER_UNAVAILABLE,
                "banking provider is unavailable",
            ) from None

    @staticmethod
    def _raise_persistence_error(error: BankingPersistenceError) -> NoReturn:
        if isinstance(error, ConfigurationNotFoundError):
            raise BankingAdministrationError(
                BankingAdministrationErrorCode.CONFIGURATION_NOT_FOUND,
                "banking provider configuration was not found",
            ) from None
        if isinstance(error, ConfigurationConflictError):
            raise BankingAdministrationError(
                BankingAdministrationErrorCode.CONFIGURATION_CONFLICT,
                "banking provider configuration changed",
            ) from None
        raise BankingAdministrationError(
            BankingAdministrationErrorCode.PERSISTENCE_FAILURE,
            "banking provider configuration could not be persisted",
        ) from None
