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


def test_connect_token_is_server_scoped_and_ephemeral() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/auth":
            assert request.method == "POST"
            assert request.headers.get("X-API-KEY") is None
            return _response(200, {"apiKey": "api-key-secret"})

        assert request.url.path == "/connect_token"
        assert request.method == "POST"
        assert request.headers["X-API-KEY"] == "api-key-secret"
        assert json.loads(request.content) == {
            "options": {
                "clientUserId": "residence:10000000-0000-4000-8000-000000000001",
                "avoidDuplicates": True,
            }
        }
        return _response(200, {"accessToken": "connect-token-secret"})

    client = _client(handler)
    with client:
        token = client.create_connect_token(
            client_user_id="residence:10000000-0000-4000-8000-000000000001"
        )
        assert token == "connect-token-secret"
        assert "connect-token-secret" not in repr(client)
        assert "api-key-secret" not in repr(client)

    assert len(requests) == 2
    assert client.api_key_loaded is False


def test_connect_token_refreshes_api_key_at_most_once() -> None:
    auth_count = 0
    token_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_count, token_count
        if request.url.path == "/auth":
            auth_count += 1
            return _response(200, {"apiKey": f"api-key-{auth_count}"})
        token_count += 1
        if token_count == 1:
            assert request.headers["X-API-KEY"] == "api-key-1"
            return _response(401, {"ignored": "sensitive"})
        assert request.headers["X-API-KEY"] == "api-key-2"
        return _response(200, {"accessToken": "connect-token"})

    with _client(handler) as client:
        assert (
            client.create_connect_token(client_user_id="residence:synthetic")
            == "connect-token"
        )

    assert auth_count == 2
    assert token_count == 2


def test_connect_token_second_auth_rejection_is_sanitized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return _response(200, {"apiKey": "api-key-secret"})
        return _response(403, {"accessToken": "must-not-leak"})

    with _client(handler) as client:
        with pytest.raises(PluggyTransportError) as captured:
            client.create_connect_token(client_user_id="residence:synthetic")

    error = captured.value
    assert error.category is PluggyTransportErrorCategory.AUTHENTICATION
    assert error.provider_reason_code == "API_KEY_REJECTED_AFTER_REFRESH"
    assert error.status_code == 403
    assert "must-not-leak" not in str(error)
    assert "api-key-secret" not in str(error)


def test_connect_token_post_is_not_replayed_after_server_failure() -> None:
    token_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_requests
        if request.url.path == "/auth":
            return _response(200, {"apiKey": "api-key"})
        token_requests += 1
        return _response(503, {"ignored": "sensitive"})

    with _client(handler) as client:
        with pytest.raises(PluggyTransportError) as captured:
            client.create_connect_token(client_user_id="residence:synthetic")

    assert token_requests == 1
    assert (
        captured.value.category is PluggyTransportErrorCategory.TEMPORARILY_UNAVAILABLE
    )
    assert captured.value.retryable is True
    assert "sensitive" not in str(captured.value)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"accessToken": None},
        {"accessToken": 123},
        {"accessToken": ""},
        {"accessToken": "   "},
    ],
)
def test_connect_token_requires_valid_access_token(payload: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return _response(200, {"apiKey": "api-key"})
        return _response(200, payload)

    with _client(handler) as client:
        with pytest.raises(PluggyTransportError) as captured:
            client.create_connect_token(client_user_id="residence:synthetic")

    assert captured.value.category is PluggyTransportErrorCategory.INVALID_RESPONSE
    assert captured.value.provider_reason_code == "CONNECT_TOKEN_MISSING"


def test_connect_token_transport_does_not_allow_items_post() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("network must not be reached")

    with _client(handler) as client:
        with pytest.raises(PluggyTransportError) as captured:
            client._request_json(
                "POST",
                "items",
                json_body={},
                authenticated=False,
            )

    assert captured.value.provider_reason_code == "ENDPOINT_NOT_ALLOWLISTED"
