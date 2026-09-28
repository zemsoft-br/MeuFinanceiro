"""Explicit fail-closed registry for banking provider factories."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TypeAlias

from .provider import BankingProvider

_PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

ProviderFactory: TypeAlias = Callable[[], BankingProvider]


class ProviderRegistryError(RuntimeError):
    """Base error with stable messages and no provider diagnostics."""


class ProviderNotRegisteredError(ProviderRegistryError):
    pass


class ProviderAlreadyRegisteredError(ProviderRegistryError):
    pass


class ProviderRegistryFrozenError(ProviderRegistryError):
    pass


class ProviderFactoryError(ProviderRegistryError):
    pass


def normalize_provider_name(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("provider_name must be a string")
    normalized = value.strip()
    if not _PROVIDER_PATTERN.fullmatch(normalized):
        raise ValueError("provider_name must be a valid provider slug")
    return normalized


class BankingProviderRegistry:
    """Registry that exposes only explicitly registered provider factories."""

    __slots__ = ("_factories", "_frozen")

    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}
        self._frozen = False

    @property
    def frozen(self) -> bool:
        return self._frozen

    def register(self, provider_name: str, factory: ProviderFactory) -> None:
        normalized = normalize_provider_name(provider_name)
        if self._frozen:
            raise ProviderRegistryFrozenError("banking provider registry is frozen")
        if not callable(factory):
            raise TypeError("provider factory must be callable")
        if normalized in self._factories:
            raise ProviderAlreadyRegisteredError(
                "banking provider is already registered"
            )
        self._factories[normalized] = factory

    def freeze(self) -> BankingProviderRegistry:
        self._frozen = True
        return self

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

    def is_registered(self, provider_name: str) -> bool:
        normalized = normalize_provider_name(provider_name)
        return normalized in self._factories

    def require_registered(self, provider_name: str) -> str:
        normalized = normalize_provider_name(provider_name)
        if normalized not in self._factories:
            raise ProviderNotRegisteredError("banking provider is not registered")
        return normalized

    def create(self, provider_name: str) -> BankingProvider:
        normalized = self.require_registered(provider_name)
        factory = self._factories[normalized]
        try:
            provider = factory()
        except Exception:
            raise ProviderFactoryError(
                "banking provider could not be created"
            ) from None
        if not isinstance(provider, BankingProvider):
            raise ProviderFactoryError(
                "banking provider factory returned an invalid provider"
            )
        try:
            actual_name = normalize_provider_name(provider.provider_name)
        except (TypeError, ValueError):
            raise ProviderFactoryError(
                "banking provider factory returned an invalid provider"
            ) from None
        if actual_name != normalized:
            raise ProviderFactoryError(
                "banking provider factory returned a mismatched provider"
            )
        return provider
