"""Session-cookie auth gate.

Runs after Starlette's `SessionMiddleware`, so `request.session` is
populated. Public paths bypass the check; everything else under `/api`
requires `uid` in the session. Non-`/api` paths (frontend SPA assets)
pass through — the SPA itself routes unauth users to `/login`.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from typing_extensions import override

PUBLIC_PATHS = frozenset(
    {
        "/api/health",
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/me",
    }
)


class SessionAuthMiddleware(BaseHTTPMiddleware):
    @override
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if not path.startswith("/api"):
            return await call_next(request)
        if path in PUBLIC_PATHS:
            return await call_next(request)
        if request.session.get("uid"):
            return await call_next(request)
        return JSONResponse(
            {"error": "unauthenticated"},
            status_code=401,
        )
