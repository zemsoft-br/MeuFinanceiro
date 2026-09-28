from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import meufinanceiro_banking
from meufinanceiro_banking import (
    BankingProvider,
    BankingProviderError,
    ProviderErrorCategory,
)

PACKAGE_ROOT = Path(meufinanceiro_banking.__file__).resolve().parent


def test_public_api_does_not_export_provider_specific_or_secret_types() -> None:
    public_names = set(meufinanceiro_banking.__all__)
    lowered = " ".join(sorted(public_names)).lower()

    for forbidden in (
        "pluggy",
        "api_key",
        "connect_token",
        "password",
        "mfa",
        "http",
        "session",
        "payload",
        "headers",
    ):
        assert forbidden not in lowered


def test_protocol_annotations_only_reference_neutral_models() -> None:
    signatures = "\n".join(
        str(inspect.signature(member))
        for name, member in inspect.getmembers(
            BankingProvider,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    ).lower()

    assert "pluggy" not in signatures
    assert "token" not in signatures
    assert "http" not in signatures
    assert "payload" not in signatures


def test_package_sources_do_not_import_external_runtime_libraries() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in PACKAGE_ROOT.glob("*.py")
    ).lower()

    for forbidden_import in (
        "import httpx",
        "import requests",
        "import fastapi",
        "import sqlalchemy",
        "import pydantic",
        "import pluggy",
    ):
        assert forbidden_import not in sources


def test_provider_error_rejects_multiline_or_oversized_diagnostics() -> None:
    with pytest.raises(ValueError, match="control characters"):
        BankingProviderError(
            ProviderErrorCategory.INTERNAL,
            retryable=False,
            provider_reason_code="unsafe\nsecret",
        )

    with pytest.raises(ValueError, match="exceeds"):
        BankingProviderError(
            ProviderErrorCategory.INTERNAL,
            retryable=False,
            safe_message="x" * 257,
        )
