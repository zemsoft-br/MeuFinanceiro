from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from meufinanceiro_banking_pluggy.transport import (
    PluggyApplicationCredentials,
    PluggyHttpTransport,
    PluggyTransportError,
    PluggyTransportErrorCategory,
)

Handler = Callable[[httpx.Request], httpx.Response]


def json_response(
    status_code: int,
    payload: object,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(status_code, json=payload, headers=headers)


def client_for(
    handler: Handler,
    *,
    sleeper: Callable[[float], None] = lambda _: None,
    jitter: Callable[[float], float] = lambda _: 0.0,
    max_response_bytes: int = 2_000_000,
) -> PluggyHttpTransport:
    return PluggyHttpTransport(
        PluggyApplicationCredentials("client-id-secret", "client-secret-secret"),
        base_url="http://127.0.0.1:8765",
        http_transport=httpx.MockTransport(handler),
        sleeper=sleeper,
        jitter=jitter,
        max_response_bytes=max_response_bytes,
    )


def test_authenticates_lazily_and_never_exposes_api_key() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/auth":
            assert request.method == "POST"
            assert request.headers.get("X-API-KEY") is None
            return json_response(
                200,
                {"apiKey": "api-key-secret"},
                headers={"Set-Cookie": "unexpected=session"},
            )
        assert request.method == "GET"
        assert request.headers["X-API-KEY"] == "api-key-secret"
        assert request.headers.get("Cookie") is None
        return json_response(200, {"id": "provider-item"})

    with client_for(handler) as client:
        assert client.api_key_loaded is False
        assert client.get_item("provider-item") == {"id": "provider-item"}
        assert client.api_key_loaded is True
        rendered = repr(client)
        assert "api-key-secret" not in rendered
        assert "client-secret-secret" not in rendered

    assert len(requests) == 2
    assert client.api_key_loaded is False


def test_accepts_legacy_access_token_authentication_field() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return json_response(200, {"accessToken": "legacy-key-secret"})
        assert request.headers["X-API-KEY"] == "legacy-key-secret"
        return json_response(200, {"results": []})

    with client_for(handler) as client:
        assert client.get_accounts("account-owner") == {"results": []}


def test_refreshes_api_key_at_most_once_after_unauthorized() -> None:
    events: list[str] = []
    auth_count = 0
    resource_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_count, resource_count
        if request.url.path == "/auth":
            auth_count += 1
            events.append(f"auth-{auth_count}")
            return json_response(200, {"apiKey": f"key-{auth_count}"})
        resource_count += 1
        events.append(f"resource-{resource_count}")
        if resource_count == 1:
            assert request.headers["X-API-KEY"] == "key-1"
            return json_response(401, {"ignored": "sensitive"})
        assert request.headers["X-API-KEY"] == "key-2"
        return json_response(200, {"results": []})

    with client_for(handler) as client:
        assert client.get_transactions("account") == {"results": []}

    assert events == ["auth-1", "resource-1", "auth-2", "resource-2"]


def test_second_unauthorized_fails_without_refresh_loop() -> None:
    auth_count = 0
    resource_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_count, resource_count
        if request.url.path == "/auth":
            auth_count += 1
            return json_response(200, {"apiKey": f"key-{auth_count}"})
        resource_count += 1
        return json_response(403, {"secret": "must-not-leak"})

    with client_for(handler) as client:
        with pytest.raises(PluggyTransportError) as captured:
            client.get_accounts("account-owner")

    error = captured.value
    assert error.category is PluggyTransportErrorCategory.AUTHENTICATION
    assert error.retryable is False
    assert error.status_code == 403
    assert error.provider_reason_code == "API_KEY_REJECTED_AFTER_REFRESH"
    assert auth_count == 2
    assert resource_count == 2
    assert "secret" not in str(error)


@pytest.mark.parametrize(
    ("headers", "expected_wait"),
    [
        ({"RateLimit-Reset": "2", "Retry-After": "9"}, 2.0),
        ({"Retry-After": "3"}, 3.0),
    ],
)
def test_rate_limit_uses_bounded_safe_window(
    headers: dict[str, str], expected_wait: float
) -> None:
    waits: list[float] = []
    resource_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal resource_count
        if request.url.path == "/auth":
            return json_response(200, {"apiKey": "key"})
        resource_count += 1
        if resource_count == 1:
            return json_response(429, {"ignored": True}, headers=headers)
        return json_response(200, {"results": []})

    with client_for(handler, sleeper=waits.append) as client:
        assert client.get_accounts("item") == {"results": []}

    assert waits == [expected_wait]
    assert resource_count == 2


def test_rate_limit_without_safe_window_does_not_retry() -> None:
    resource_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal resource_count
        if request.url.path == "/auth":
            return json_response(200, {"apiKey": "key"})
        resource_count += 1
        return json_response(429, {"ignored": True}, headers={"Retry-After": "999"})

    with client_for(handler) as client:
        with pytest.raises(PluggyTransportError) as captured:
            client.get_accounts("item")

    assert captured.value.category is PluggyTransportErrorCategory.RATE_LIMITED
    assert captured.value.retryable is False
    assert resource_count == 1


def test_server_errors_use_bounded_exponential_backoff() -> None:
    waits: list[float] = []
    resource_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal resource_count
        if request.url.path == "/auth":
            return json_response(200, {"apiKey": "key"})
        resource_count += 1
        if resource_count < 3:
            return json_response(503, {"ignored": True})
        return json_response(200, {"results": []})

    with client_for(handler, sleeper=waits.append) as client:
        assert client.get_accounts("item") == {"results": []}

    assert waits == [0.5, 1.0]
    assert resource_count == 3


def test_network_errors_are_retried_and_sanitized() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        raise httpx.ConnectError(
            "client-secret-secret at https://sensitive.invalid/path",
            request=request,
        )

    with client_for(handler) as client:
        with pytest.raises(PluggyTransportError) as captured:
            client.get_item("item-sensitive-id")

    error = captured.value
    assert error.category is PluggyTransportErrorCategory.TEMPORARILY_UNAVAILABLE
    assert error.retryable is True
    assert requests == 3
    rendered = f"{error!s} {error!r}"
    assert "client-secret-secret" not in rendered
    assert "sensitive.invalid" not in rendered
    assert "item-sensitive-id" not in rendered


@pytest.mark.parametrize(
    ("status_code", "category"),
    [
        (400, PluggyTransportErrorCategory.INVALID_REQUEST),
        (404, PluggyTransportErrorCategory.NOT_FOUND),
    ],
)
def test_functional_client_errors_are_not_retried(
    status_code: int,
    category: PluggyTransportErrorCategory,
) -> None:
    resource_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal resource_count
        if request.url.path == "/auth":
            return json_response(200, {"apiKey": "key"})
        resource_count += 1
        return json_response(status_code, {"raw": "must-not-leak"})

    with client_for(handler) as client:
        with pytest.raises(PluggyTransportError) as captured:
            client.get_accounts("item")

    assert captured.value.category is category
    assert captured.value.retryable is False
    assert resource_count == 1
    assert "must-not-leak" not in str(captured.value)


def test_rejects_oversized_response_before_parsing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return json_response(200, {"apiKey": "key"})
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=b'{"value":"0123456789"}',
        )

    with client_for(handler, max_response_bytes=10) as client:
        with pytest.raises(PluggyTransportError) as captured:
            client.get_item("item")

    assert captured.value.provider_reason_code == "RESPONSE_TOO_LARGE"


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (
            httpx.Response(
                200,
                headers={"Content-Type": "text/plain"},
                content=b"not-json",
            ),
            "UNEXPECTED_CONTENT_TYPE",
        ),
        (
            httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=b"not-json",
            ),
            "INVALID_JSON",
        ),
        (
            httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json=[1, 2, 3],
            ),
            "UNEXPECTED_JSON_SHAPE",
        ),
        (
            httpx.Response(
                302,
                headers={"Location": "https://sensitive.invalid/redirect"},
            ),
            "UNEXPECTED_HTTP_STATUS",
        ),
    ],
)
def test_invalid_responses_fail_closed(
    response: httpx.Response,
    reason: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return json_response(200, {"apiKey": "key"})
        return response

    with client_for(handler) as client:
        with pytest.raises(PluggyTransportError) as captured:
            client.get_item("item")

    assert captured.value.category is PluggyTransportErrorCategory.INVALID_RESPONSE
    assert captured.value.provider_reason_code == reason
    assert "sensitive.invalid" not in str(captured.value)


def test_authentication_payload_must_contain_a_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(200, {"unexpected": "client-secret-secret"})

    with client_for(handler) as client:
        with pytest.raises(PluggyTransportError) as captured:
            client.get_item("item")

    assert captured.value.provider_reason_code == "AUTH_KEY_MISSING"
    assert "client-secret-secret" not in str(captured.value)


def test_credentials_and_transport_representations_are_redacted() -> None:
    credentials = PluggyApplicationCredentials(
        "client-id-secret",
        "client-secret-secret",
    )
    assert repr(credentials) == "PluggyApplicationCredentials(<redacted>)"

    with PluggyHttpTransport(
        credentials,
        base_url="http://localhost:8765",
        http_transport=httpx.MockTransport(
            lambda request: json_response(200, {"apiKey": "key"})
        ),
    ) as client:
        rendered = repr(client)
        assert "client-id-secret" not in rendered
        assert "client-secret-secret" not in rendered


def test_production_base_url_is_fixed_and_http_is_loopback_only() -> None:
    credentials = PluggyApplicationCredentials("client", "secret")
    with pytest.raises(ValueError, match="fixed Pluggy production host"):
        PluggyHttpTransport(credentials, base_url="https://example.com")
    with pytest.raises(ValueError, match="HTTPS outside loopback"):
        PluggyHttpTransport(credentials, base_url="http://example.com")


def test_closed_transport_fails_closed_without_credentials() -> None:
    client = client_for(lambda request: json_response(200, {"apiKey": "key"}))
    client.close()
    with pytest.raises(PluggyTransportError) as captured:
        client.get_item("item")
    assert captured.value.provider_reason_code == "TRANSPORT_CLOSED"


def test_query_parameters_are_bound_to_allowlisted_operations() -> None:
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        if request.url.path == "/auth":
            return json_response(200, {"apiKey": "key"})
        return json_response(200, {"results": []})

    with client_for(handler) as client:
        client.get_accounts("item/id")
        client.get_transactions("account/id", cursor="opaque/cursor")

    accounts = observed[1]
    transactions = observed[2]
    assert accounts.url.path == "/accounts"
    assert dict(accounts.url.params) == {"itemId": "item/id"}
    assert transactions.url.path == "/v2/transactions"
    assert dict(transactions.url.params) == {
        "accountId": "account/id",
        "cursor": "opaque/cursor",
    }
