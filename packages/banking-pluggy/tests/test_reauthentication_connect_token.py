from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from meufinanceiro_banking_pluggy import PluggyConnectTokenHttpTransport
from meufinanceiro_banking_pluggy.transport import (
    PluggyApplicationCredentials,
    PluggyTransportError,
    PluggyTransportErrorCategory,
)

Handler = Callable[[httpx.Request], httpx.Response]
ITEM_ID = "synthetic-existing-item"


def _response(status_code: int, payload: object) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


def _client(handler: Handler) -> PluggyConnectTokenHttpTransport:
    return PluggyConnectTokenHttpTransport(
        PluggyApplicationCredentials("client-id-secret", "client-secret-secret"),
        base_url="http://127.0.0.1:8765",
        http_transport=httpx.MockTransport(handler),
        sleeper=lambda _: None,
        jitter=lambda _: 0.0,
    )


def test_update_connect_token_sends_only_verified_item_id() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/auth":
            return _response(200, {"apiKey": "api-key-secret"})
        assert request.url.path == "/connect_token"
        assert request.method == "POST"
        assert request.headers["X-API-KEY"] == "api-key-secret"
        assert json.loads(request.content) == {"itemId": ITEM_ID}
        return _response(200, {"accessToken": "update-connect-token-secret"})

    with _client(handler) as client:
        token = client.create_update_connect_token(item_id=ITEM_ID)

    assert token == "update-connect-token-secret"
    assert len(requests) == 2


def test_update_connect_token_does_not_replay_ambiguous_server_failure() -> None:
    token_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_requests
        if request.url.path == "/auth":
            return _response(200, {"apiKey": "api-key"})
        token_requests += 1
        return _response(503, {"ignored": "provider-payload"})

    with _client(handler) as client:
        with pytest.raises(PluggyTransportError) as captured:
            client.create_update_connect_token(item_id=ITEM_ID)

    assert token_requests == 1
    assert (
        captured.value.category
        is PluggyTransportErrorCategory.TEMPORARILY_UNAVAILABLE
    )
    assert "provider-payload" not in str(captured.value)
    assert ITEM_ID not in str(captured.value)


def test_update_connect_token_refreshes_api_key_at_most_once() -> None:
    auth_count = 0
    token_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_count, token_count
        if request.url.path == "/auth":
            auth_count += 1
            return _response(200, {"apiKey": f"api-key-{auth_count}"})
        token_count += 1
        if token_count == 1:
            return _response(401, {"ignored": "provider-payload"})
        return _response(200, {"accessToken": "update-token"})

    with _client(handler) as client:
        assert client.create_update_connect_token(item_id=ITEM_ID) == "update-token"

    assert auth_count == 2
    assert token_count == 2


def test_update_connect_token_rejects_unsafe_item_id_before_network() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("network must not be reached")

    with _client(handler) as client:
        with pytest.raises(ValueError):
            client.create_update_connect_token(item_id="   ")
