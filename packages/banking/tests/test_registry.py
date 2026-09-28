from __future__ import annotations

import pytest

from meufinanceiro_banking import (
    BankingProviderRegistry,
    FakeBankingProvider,
    ProviderAlreadyRegisteredError,
    ProviderFactoryError,
    ProviderNotRegisteredError,
    ProviderRegistryFrozenError,
)


class MismatchedFakeProvider(FakeBankingProvider):
    @property
    def provider_name(self) -> str:
        return "other"


def test_registry_is_empty_and_fail_closed_by_default() -> None:
    registry = BankingProviderRegistry()

    assert registry.names() == ()
    assert registry.is_registered("fake") is False
    with pytest.raises(ProviderNotRegisteredError, match="not registered"):
        registry.require_registered("fake")
    with pytest.raises(ProviderNotRegisteredError, match="not registered"):
        registry.create("fake")


def test_registry_registers_and_creates_matching_provider() -> None:
    registry = BankingProviderRegistry()
    registry.register("fake", FakeBankingProvider)

    assert registry.names() == ("fake",)
    assert registry.is_registered("fake") is True
    assert registry.create("fake").provider_name == "fake"


def test_registry_rejects_duplicates_and_registration_after_freeze() -> None:
    registry = BankingProviderRegistry()
    registry.register("fake", FakeBankingProvider)

    with pytest.raises(ProviderAlreadyRegisteredError, match="already registered"):
        registry.register("fake", FakeBankingProvider)

    assert registry.freeze() is registry
    assert registry.frozen is True
    with pytest.raises(ProviderRegistryFrozenError, match="frozen"):
        registry.register("other", FakeBankingProvider)


def test_registry_validates_provider_slugs() -> None:
    registry = BankingProviderRegistry()

    for provider_name in ("", " Fake", "pluggy-http", "UPPER", "a" * 64):
        with pytest.raises(ValueError, match="provider slug"):
            registry.is_registered(provider_name)


def test_registry_rejects_invalid_or_mismatched_factories() -> None:
    invalid_registry = BankingProviderRegistry()
    invalid_registry.register("fake", lambda: object())  # type: ignore[arg-type,return-value]

    with pytest.raises(ProviderFactoryError, match="invalid provider"):
        invalid_registry.create("fake")

    mismatched_registry = BankingProviderRegistry()
    mismatched_registry.register("fake", MismatchedFakeProvider)

    with pytest.raises(ProviderFactoryError, match="mismatched provider"):
        mismatched_registry.create("fake")


def test_registry_sanitizes_factory_failures() -> None:
    registry = BankingProviderRegistry()

    def broken_factory() -> FakeBankingProvider:
        raise RuntimeError("provider-secret-diagnostic")

    registry.register("fake", broken_factory)

    with pytest.raises(ProviderFactoryError) as captured:
        registry.create("fake")

    assert str(captured.value) == "banking provider could not be created"
    assert "provider-secret-diagnostic" not in str(captured.value)
    assert captured.value.__cause__ is None
