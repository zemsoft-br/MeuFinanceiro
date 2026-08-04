from __future__ import annotations

import httpx
import pytest

from meufinanceiro_banking_pluggy.transport import (
    PluggyApplicationCredentials,
    PluggyHttpTransport,
    PluggyTransportError,
    PluggyTransportErrorCategory,
)


def test_malformed_authentication_key_fails_with_sanitized_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/auth"
        return httpx.Response(200, json={"apiKey": "malformed\x00secret"})

    with PluggyHttpTransport(
        PluggyApplicationCredentials("client-id", "client-secret"),
        base_url="http://127.0.0.1:8765",
        http_transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(PluggyTransportError) as captured:
            client.get_item("item")

    error = captured.value
    assert error.category is PluggyTransportErrorCategory.INVALID_RESPONSE
    assert error.retryable is False
    assert error.provider_reason_code == "AUTH_KEY_INVALID"
    assert "malformed" not in str(error)
    assert "secret" not in str(error)


def test_item_path_identifier_rejects_delimiters_before_http() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"apiKey": "key"})

    with PluggyHttpTransport(
        PluggyApplicationCredentials("client-id", "client-secret"),
        base_url="http://localhost:8765",
        http_transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(ValueError, match="path delimiters"):
            client.get_item("item/other")

    assert calls == 0
