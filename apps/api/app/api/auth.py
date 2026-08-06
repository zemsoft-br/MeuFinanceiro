"""FastAPI dependency and cache policy for opaque operator sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Header, HTTPException, Request, status
from meufinanceiro_persistence import OperatorSessionPrincipal
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.services.operator_auth import (
    InvalidOperatorSessionError,
    OperatorAuthenticationService,
    OperatorAuthenticationUnavailableError,
)


@dataclass(frozen=True, slots=True, repr=False)
class AuthenticatedOperatorRequest:
    token: str
    principal: OperatorSessionPrincipal

    def __repr__(self) -> str:
        return (
            "AuthenticatedOperatorRequest("
            f"principal={self.principal!r}, token=<redacted>)"
        )


class AuthenticationNoStoreMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/api/v1/auth/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="operator authentication is required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="operator authentication is unavailable",
    )


def require_operator_session(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> AuthenticatedOperatorRequest:
    if not isinstance(authorization, str):
        raise _unauthorized()
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token:
        raise _unauthorized()
    if token != token.strip() or " " in token:
        raise _unauthorized()
    service: OperatorAuthenticationService = request.app.state.operator_authentication
    try:
        principal = service.resolve(token)
    except InvalidOperatorSessionError:
        raise _unauthorized() from None
    except OperatorAuthenticationUnavailableError:
        raise _unavailable() from None
    return AuthenticatedOperatorRequest(token=token, principal=principal)
