"""CSRF protection and security headers.

Auth uses a SameSite=Lax HttpOnly cookie. As a second layer, every state-changing
API request must carry the custom header `X-Requested-With`. Browsers cannot send
custom headers cross-origin without a CORS preflight, which our CORS policy only
allows for FRONTEND_ORIGIN, so forged form posts from other sites are rejected."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class CSRFHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if (
            request.method not in SAFE_METHODS
            and request.url.path.startswith("/api/")
            and not request.headers.get("x-requested-with")
        ):
            return JSONResponse(status_code=403, content={"detail": "Missing X-Requested-With header"})
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.url.path.startswith("/uploads/"):
            response.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; sandbox"
            response.headers["Cache-Control"] = "public, max-age=86400"
        return response
