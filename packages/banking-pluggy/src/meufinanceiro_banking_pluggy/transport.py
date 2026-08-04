"""Bounded Pluggy HTTP transport with ephemeral authentication."""

from __future__ import annotations

import ipaddress
import json
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import TracebackType
from typing import Final, TypeAlias, cast
from urllib.parse import quote, urlsplit

import httpx

_DEFAULT_BASE_URL: Final = "https://api.pluggy.ai"
_MAX_ATTEMPTS: Final = 3
_RETRY_BASE_SECONDS: Final = 0.5
_RETRY_MAX_SECONDS: Final = 4.0
_MAX_RATE_LIMIT_WAIT_SECONDS: Final = 60.0
_DEFAULT_MAX_RESPONSE_BYTES: Final = 2_000_000
_MAX_IDENTIFIER_LENGTH: Final = 512
_MAX_CURSOR_LENGTH: Final = 4096
_MAX_SECRET_LENGTH: Final = 4096
_MAX_REASON_CODE_LENGTH: Final = 128

JsonObject: TypeAlias = dict[str, object]
Sleeper: TypeAlias = Callable[[float], None]
Jitter: TypeAlias = Callable[[float], float]


class PluggyTransportErrorCategory(StrEnum):
    """Stable transport-level error categories without raw diagnostics."""

    AUTHENTICATION = "AUTHENTICATION"
    AUTHORIZATION = "AUTHORIZATION"
    NOT_FOUND = "NOT_FOUND"
    INVALID_REQUEST = "INVALID_REQUEST"
    RATE_LIMITED = "RATE_LIMITED"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    INTERNAL = "INTERNAL"


class PluggyTransportError(RuntimeError):
    """Sanitized transport failure safe to cross internal package boundaries."""

    __slots__ = ("category", "provider_reason_code", "retryable", "status_code")

    def __init__(
        self,
        category: PluggyTransportErrorCategory,
        *,
        retryable: bool,
        status_code: int | None = None,
        provider_reason_code: str | None = None,
    ) -> None:
        if not isinstance(category, PluggyTransportErrorCategory):
            raise TypeError("category must be PluggyTransportErrorCategory")
        if not isinstance(retryable, bool):
            raise TypeError("retryable must be bool")
        if status_code is not None and not 100 <= status_code <= 599:
            raise ValueError("status_code must be a valid HTTP status")
        reason = _clean_optional_reason_code(provider_reason_code)
        super().__init__("pluggy transport operation failed")
        self.category = category
        self.retryable = retryable
        self.status_code = status_code
        self.provider_reason_code = reason


@dataclass(frozen=True, slots=True, repr=False)
class PluggyApplicationCredentials:
    """Application credentials retained only by the transport instance."""

    client_id: str
    client_secret: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "client_id",
            _clean_secret(self.client_id, "client_id"),
        )
        object.__setattr__(
            self,
            "client_secret",
            _clean_secret(self.client_secret, "client_secret"),
        )

    def __repr__(self) -> str:
        return "PluggyApplicationCredentials(<redacted>)"


class _AuthenticationRejected(RuntimeError):
    __slots__ = ("status_code",)

    def __init__(self, status_code: int) -> None:
        super().__init__("authenticated request rejected")
        self.status_code = status_code


def _clean_text(value: str, field_name: str, *, max_length: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} exceeds the maximum length")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ValueError(f"{field_name} contains control characters")
    return normalized


def _clean_secret(value: str, field_name: str) -> str:
    return _clean_text(value, field_name, max_length=_MAX_SECRET_LENGTH)


def _clean_identifier(value: str, field_name: str) -> str:
    return _clean_text(value, field_name, max_length=_MAX_IDENTIFIER_LENGTH)


def _clean_path_identifier(value: str, field_name: str) -> str:
    identifier = _clean_identifier(value, field_name)
    if any(character in identifier for character in ("/", "\\", "?", "#")):
        raise ValueError(f"{field_name} contains path delimiters")
    return identifier


def _clean_cursor(value: str | None) -> str | None:
    if value is None:
        return None
    return _clean_text(value, "cursor", max_length=_MAX_CURSOR_LENGTH)


def _clean_optional_reason_code(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _clean_text(
        value,
        "provider_reason_code",
        max_length=_MAX_REASON_CODE_LENGTH,
    )
    if not all(
        character.isascii() and (character.isalnum() or character in "_-")
        for character in normalized
    ):
        raise ValueError("provider_reason_code contains unsupported characters")
    return normalized


def _default_jitter(delay: float) -> float:
    ceiling = min(delay * 0.25, 1.0)
    if ceiling <= 0:
        return 0.0
    return secrets.randbelow(10_001) / 10_000 * ceiling


def _backoff_seconds(attempt: int, jitter: Jitter) -> float:
    base = min(_RETRY_MAX_SECONDS, _RETRY_BASE_SECONDS * (2 ** (attempt - 1)))
    return float(min(_RETRY_MAX_SECONDS, base + max(0.0, jitter(base))))


def _positive_wait_seconds(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw.strip())
    except ValueError:
        return None
    if value <= 0 or value > _MAX_RATE_LIMIT_WAIT_SECONDS:
        return None
    return value


def _rate_limit_wait(headers: httpx.Headers) -> float | None:
    reset = _positive_wait_seconds(headers.get("RateLimit-Reset"))
    if reset is not None:
        return reset
    return _positive_wait_seconds(headers.get("Retry-After"))


def _is_loopback_host(hostname: str) -> bool:
    if hostname.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _validated_base_url(value: str) -> str:
    normalized = _clean_text(value, "base_url", max_length=2048).rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("base_url must not contain user information")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("base_url must contain only scheme, host, and optional port")
    hostname = parsed.hostname
    if hostname is None:
        raise ValueError("base_url must contain a host")
    if parsed.scheme == "https":
        if hostname.casefold() != "api.pluggy.ai" or parsed.port not in {None, 443}:
            raise ValueError("base_url must use the fixed Pluggy production host")
        return normalized
    if parsed.scheme != "http" or not _is_loopback_host(hostname):
        raise ValueError("base_url must use HTTPS outside loopback tests")
    return normalized


def _is_json_content_type(value: str | None) -> bool:
    if value is None:
        return False
    media_type = value.split(";", 1)[0].strip().casefold()
    return media_type == "application/json" or media_type.endswith("+json")


class PluggyHttpTransport:
    """Allowlisted Pluggy transport with bounded retry and one key refresh."""

    def __init__(
        self,
        credentials: PluggyApplicationCredentials,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        http_transport: httpx.BaseTransport | None = None,
        sleeper: Sleeper = time.sleep,
        jitter: Jitter = _default_jitter,
        max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        if not isinstance(credentials, PluggyApplicationCredentials):
            raise TypeError("credentials must be PluggyApplicationCredentials")
        if not callable(sleeper) or not callable(jitter):
            raise TypeError("sleeper and jitter must be callable")
        if not 1 <= max_response_bytes <= 10_000_000:
            raise ValueError("max_response_bytes is outside the supported range")
        validated_base_url = _validated_base_url(base_url)
        self._credentials: PluggyApplicationCredentials | None = credentials
        self._api_key: str | None = None
        self._sleeper = sleeper
        self._jitter = jitter
        self._max_response_bytes = max_response_bytes
        self._closed = False
        self._client = httpx.Client(
            base_url=f"{validated_base_url}/",
            headers={
                "Accept": "application/json",
                "User-Agent": "MeuFinanceiro-Pluggy-Transport/1",
            },
            timeout=httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=5.0),
            follow_redirects=False,
            transport=http_transport,
            trust_env=False,
        )

    def __repr__(self) -> str:
        state = "closed" if self._closed else "open"
        authenticated = self._api_key is not None
        return f"PluggyHttpTransport(state={state!r}, authenticated={authenticated!r})"

    def __enter__(self) -> PluggyHttpTransport:
        self._ensure_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        self.close()

    @property
    def api_key_loaded(self) -> bool:
        """Expose only key presence, never the key value."""

        return self._api_key is not None

    def close(self) -> None:
        if self._closed:
            return
        self._api_key = None
        self._credentials = None
        self._client.cookies.clear()
        self._client.close()
        self._closed = True

    def get_item(self, item_id: str) -> JsonObject:
        identifier = _clean_path_identifier(item_id, "item_id")
        encoded = quote(identifier, safe="")
        return self._authenticated_get(f"items/{encoded}")

    def get_accounts(self, item_id: str) -> JsonObject:
        identifier = _clean_identifier(item_id, "item_id")
        return self._authenticated_get("accounts", params={"itemId": identifier})

    def get_transactions(
        self,
        account_id: str,
        *,
        cursor: str | None = None,
    ) -> JsonObject:
        identifier = _clean_identifier(account_id, "account_id")
        normalized_cursor = _clean_cursor(cursor)
        params = {"accountId": identifier}
        if normalized_cursor is not None:
            params["cursor"] = normalized_cursor
        return self._authenticated_get("v2/transactions", params=params)

    def _ensure_open(self) -> None:
        if self._closed:
            raise PluggyTransportError(
                PluggyTransportErrorCategory.INTERNAL,
                retryable=False,
                provider_reason_code="TRANSPORT_CLOSED",
            )

    def _authenticate(self) -> None:
        self._ensure_open()
        credentials = self._credentials
        if credentials is None:
            raise PluggyTransportError(
                PluggyTransportErrorCategory.INTERNAL,
                retryable=False,
                provider_reason_code="CREDENTIALS_UNAVAILABLE",
            )
        try:
            payload = self._request_json(
                "POST",
                "auth",
                json_body={
                    "clientId": credentials.client_id,
                    "clientSecret": credentials.client_secret,
                },
                authenticated=False,
            )
        except _AuthenticationRejected as exc:
            raise PluggyTransportError(
                PluggyTransportErrorCategory.AUTHENTICATION,
                retryable=False,
                status_code=exc.status_code,
                provider_reason_code="APPLICATION_CREDENTIALS_REJECTED",
            ) from None
        value = payload.get("apiKey")
        if not isinstance(value, str) or not value.strip():
            value = payload.get("accessToken")
        if not isinstance(value, str) or not value.strip():
            raise PluggyTransportError(
                PluggyTransportErrorCategory.INVALID_RESPONSE,
                retryable=False,
                provider_reason_code="AUTH_KEY_MISSING",
            )
        try:
            self._api_key = _clean_secret(value, "api_key")
        except (TypeError, ValueError):
            raise PluggyTransportError(
                PluggyTransportErrorCategory.INVALID_RESPONSE,
                retryable=False,
                provider_reason_code="AUTH_KEY_INVALID",
            ) from None

    def _authenticated_get(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
    ) -> JsonObject:
        self._ensure_open()
        if self._api_key is None:
            self._authenticate()
        try:
            return self._request_json(
                "GET",
                path,
                params=params,
                authenticated=True,
            )
        except _AuthenticationRejected:
            self._api_key = None
            self._authenticate()
            try:
                return self._request_json(
                    "GET",
                    path,
                    params=params,
                    authenticated=True,
                )
            except _AuthenticationRejected as exc:
                self._api_key = None
                raise PluggyTransportError(
                    PluggyTransportErrorCategory.AUTHENTICATION,
                    retryable=False,
                    status_code=exc.status_code,
                    provider_reason_code="API_KEY_REJECTED_AFTER_REFRESH",
                ) from None

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: Mapping[str, str] | None = None,
        authenticated: bool,
    ) -> JsonObject:
        self._ensure_open()
        self._validate_operation(method, path)
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            headers = self._authentication_headers(authenticated)
            try:
                with self._client.stream(
                    method,
                    path,
                    params=params,
                    json=json_body,
                    headers=headers,
                ) as response:
                    self._client.cookies.clear()
                    result = self._handle_response(response, attempt)
                    if result is not None:
                        return result
            except _AuthenticationRejected:
                raise
            except PluggyTransportError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt < _MAX_ATTEMPTS:
                    self._sleep_backoff(attempt)
                    continue
                raise PluggyTransportError(
                    PluggyTransportErrorCategory.TEMPORARILY_UNAVAILABLE,
                    retryable=True,
                    provider_reason_code="NETWORK_RETRY_EXHAUSTED",
                ) from None
            except httpx.HTTPError:
                raise PluggyTransportError(
                    PluggyTransportErrorCategory.INTERNAL,
                    retryable=False,
                    provider_reason_code="HTTP_CLIENT_FAILURE",
                ) from None
        raise PluggyTransportError(
            PluggyTransportErrorCategory.INTERNAL,
            retryable=False,
            provider_reason_code="NO_RESPONSE",
        )

    def _validate_operation(self, method: str, path: str) -> None:
        if method not in {"GET", "POST"}:
            raise PluggyTransportError(
                PluggyTransportErrorCategory.INTERNAL,
                retryable=False,
                provider_reason_code="METHOD_NOT_ALLOWLISTED",
            )
        if method == "POST" and path != "auth":
            raise PluggyTransportError(
                PluggyTransportErrorCategory.INTERNAL,
                retryable=False,
                provider_reason_code="ENDPOINT_NOT_ALLOWLISTED",
            )
        if (
            method == "GET"
            and path not in {"accounts", "v2/transactions"}
            and not path.startswith("items/")
        ):
            raise PluggyTransportError(
                PluggyTransportErrorCategory.INTERNAL,
                retryable=False,
                provider_reason_code="ENDPOINT_NOT_ALLOWLISTED",
            )

    def _authentication_headers(self, authenticated: bool) -> dict[str, str]:
        if not authenticated:
            return {}
        api_key = self._api_key
        if api_key is None:
            raise PluggyTransportError(
                PluggyTransportErrorCategory.INTERNAL,
                retryable=False,
                provider_reason_code="API_KEY_UNAVAILABLE",
            )
        return {"X-API-KEY": api_key}

    def _handle_response(
        self,
        response: httpx.Response,
        attempt: int,
    ) -> JsonObject | None:
        status_code = response.status_code
        if 200 <= status_code <= 299:
            return self._decode_response(response)
        if status_code in {401, 403}:
            raise _AuthenticationRejected(status_code)
        if status_code == 429:
            wait_seconds = _rate_limit_wait(response.headers)
            if attempt < _MAX_ATTEMPTS and wait_seconds is not None:
                self._sleeper(wait_seconds)
                return None
            raise PluggyTransportError(
                PluggyTransportErrorCategory.RATE_LIMITED,
                retryable=wait_seconds is not None,
                status_code=status_code,
                provider_reason_code=(
                    "RATE_LIMIT_RETRY_EXHAUSTED"
                    if wait_seconds is not None
                    else "RATE_LIMIT_WINDOW_UNAVAILABLE"
                ),
            )
        if 500 <= status_code <= 599:
            if attempt < _MAX_ATTEMPTS:
                self._sleep_backoff(attempt)
                return None
            raise PluggyTransportError(
                PluggyTransportErrorCategory.TEMPORARILY_UNAVAILABLE,
                retryable=True,
                status_code=status_code,
                provider_reason_code="SERVER_RETRY_EXHAUSTED",
            )
        if status_code == 404:
            raise PluggyTransportError(
                PluggyTransportErrorCategory.NOT_FOUND,
                retryable=False,
                status_code=status_code,
                provider_reason_code="RESOURCE_NOT_FOUND",
            )
        if 400 <= status_code <= 499:
            raise PluggyTransportError(
                PluggyTransportErrorCategory.INVALID_REQUEST,
                retryable=False,
                status_code=status_code,
                provider_reason_code="REQUEST_REJECTED",
            )
        raise PluggyTransportError(
            PluggyTransportErrorCategory.INVALID_RESPONSE,
            retryable=False,
            status_code=status_code,
            provider_reason_code="UNEXPECTED_HTTP_STATUS",
        )

    def _sleep_backoff(self, attempt: int) -> None:
        self._sleeper(_backoff_seconds(attempt, self._jitter))

    def _decode_response(self, response: httpx.Response) -> JsonObject:
        if not _is_json_content_type(response.headers.get("Content-Type")):
            raise PluggyTransportError(
                PluggyTransportErrorCategory.INVALID_RESPONSE,
                retryable=False,
                status_code=response.status_code,
                provider_reason_code="UNEXPECTED_CONTENT_TYPE",
            )
        body = bytearray()
        for chunk in response.iter_bytes():
            if len(body) + len(chunk) > self._max_response_bytes:
                raise PluggyTransportError(
                    PluggyTransportErrorCategory.INVALID_RESPONSE,
                    retryable=False,
                    status_code=response.status_code,
                    provider_reason_code="RESPONSE_TOO_LARGE",
                )
            body.extend(chunk)
        try:
            decoded = json.loads(bytes(body))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise PluggyTransportError(
                PluggyTransportErrorCategory.INVALID_RESPONSE,
                retryable=False,
                status_code=response.status_code,
                provider_reason_code="INVALID_JSON",
            ) from None
        if not isinstance(decoded, dict) or not all(
            isinstance(key, str) for key in decoded
        ):
            raise PluggyTransportError(
                PluggyTransportErrorCategory.INVALID_RESPONSE,
                retryable=False,
                status_code=response.status_code,
                provider_reason_code="UNEXPECTED_JSON_SHAPE",
            )
        return cast(JsonObject, decoded)
