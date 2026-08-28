"""Bearer-token auth guard.

Enabled only when ``BS_AUTH_TOKEN`` is set. When enabled:

- ``/api/*`` requests require ``Authorization: Bearer {token}``.
- ``/healthz`` is always public (used by container healthchecks / probes).
- The kiosk HTML pages (``/``, ``/dashboard``, ``/static/*``) are exempt so
  the LAN-only single-household use case still works without pushing a token
  into the browser.

Never bypass verification. Never store the token in the repo.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_settings

_PUBLIC_PREFIXES = ("/healthz", "/static/", "/docs", "/redoc", "/openapi.json")
_PROTECTED_PREFIX = "/api/"


class BearerTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable],
    ):
        token = get_settings().auth_token
        if not token:
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES):
            return await call_next(request)
        if not path.startswith(_PROTECTED_PREFIX):
            return await call_next(request)

        header = request.headers.get("authorization", "")
        expected = f"Bearer {token}"
        if header != expected:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid bearer token."},
                headers={"WWW-Authenticate": 'Bearer realm="bleepstash"'},
            )
        return await call_next(request)
