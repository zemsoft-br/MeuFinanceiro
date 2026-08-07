"""Bounded Pluggy Connect Token transport built on the authenticated HTTP core."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import httpx

from .transport import (
    JsonObject,
    PluggyHttpTransport,
    PluggyTransportError,
    PluggyTransportErrorCategory,
    _AuthenticationRejected,
    _MAX_ATTEMPTS,
    _clean_identifier,
    _clean_secret,
)


class PluggyConnectTokenHttpTransport(PluggyHttpTransport):
    """Issue one server-authorized Connect Token without broadening other POSTs."""

    def create_connect_token(self, *, client_user_id: str) -> str:
        normalized_client_user_id = _clean_identifier(
            client_user_id,
            "client_user_id",
        )
        payload = cast(
            Mapping[str, str],
            {
                "options": {
                    "clientUserId": normalized_client_user_id,
                    "avoidDuplicates": True,
                }
            },
        )
        response = self._authenticated_connect_token(payload)
        value = response.get("accessToken")
        if not isinstance(value, str) or not value.strip():
            raise PluggyTransportError(
                PluggyTransportErrorCategory.INVALID_RESPONSE,
                retryable=False,
                provider_reason_code="CONNECT_TOKEN_MISSING",
            )
        try:
            return _clean_secret(value, "connect_token")
        except (TypeError, ValueError):
            raise PluggyTransportError(
                PluggyTransportErrorCategory.INVALID_RESPONSE,
                retryable=False,
                provider_reason_code="CONNECT_TOKEN_INVALID",
            ) from None

    def _authenticated_connect_token(
        self,
        payload: Mapping[str, str],
    ) -> JsonObject:
        self._ensure_open()
        if self._api_key is None:
            self._authenticate()
        try:
            return self._request_connect_token_once(payload)
        except _AuthenticationRejected:
            self._api_key = None
            self._authenticate()
            try:
                return self._request_connect_token_once(payload)
            except _AuthenticationRejected as exc:
                self._api_key = None
                raise PluggyTransportError(
                    PluggyTransportErrorCategory.AUTHENTICATION,
                    retryable=False,
                    status_code=exc.status_code,
                    provider_reason_code="API_KEY_REJECTED_AFTER_REFRESH",
                ) from None

    def _request_connect_token_once(
        self,
        payload: Mapping[str, str],
    ) -> JsonObject:
        self._ensure_open()
        self._validate_operation("POST", "connect_token")
        headers = self._authentication_headers(True)
        try:
            with self._client.stream(
                "POST",
                "connect_token",
                json=payload,
                headers=headers,
            ) as response:
                self._client.cookies.clear()
                result = self._handle_response(response, _MAX_ATTEMPTS)
                if result is not None:
                    return result
        except _AuthenticationRejected:
            raise
        except PluggyTransportError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError):
            raise PluggyTransportError(
                PluggyTransportErrorCategory.TEMPORARILY_UNAVAILABLE,
                retryable=True,
                provider_reason_code="CONNECT_TOKEN_NETWORK_FAILURE",
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
        if method == "POST" and path == "connect_token":
            return
        super()._validate_operation(method, path)
