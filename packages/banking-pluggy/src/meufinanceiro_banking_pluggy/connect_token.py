"""Bounded Pluggy Connect Token transport built on the authenticated HTTP core."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from .transport import (
    JsonObject,
    PluggyHttpTransport,
    PluggyTransportError,
    PluggyTransportErrorCategory,
    _AuthenticationRejected,
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
            return self._request_json(
                "POST",
                "connect_token",
                json_body=payload,
                authenticated=True,
            )
        except _AuthenticationRejected:
            self._api_key = None
            self._authenticate()
            try:
                return self._request_json(
                    "POST",
                    "connect_token",
                    json_body=payload,
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

    def _validate_operation(self, method: str, path: str) -> None:
        if method == "POST" and path == "connect_token":
            return
        super()._validate_operation(method, path)
