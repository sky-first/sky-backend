"""Defence-in-depth HTTP response headers.

Red-team (infra 2026-04-23): baseline GETs were missing HSTS, CSP,
X-Content-Type-Options, X-Frame-Options, Referrer-Policy, and COOP.
Also the stock `Server: uvicorn` header leaks the stack.

This middleware sets the full set on every response and drops the
server header. Values are conservative defaults; ops can override via
env when a site-specific CSP is ready.
"""

from __future__ import annotations

import os
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


def _default(name: str, fallback: str) -> str:
    return os.environ.get(name) or fallback


# Conservative CSP: allow same-origin only. Staging is server-rendered
# by Next.js elsewhere; here we serve JSON. Any override goes via env.
_DEFAULT_CSP = (
    "default-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "img-src 'self' data:; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        response: Response = await call_next(request)
        headers = response.headers

        # Transport / MIME.
        headers.setdefault(
            "strict-transport-security",
            _default(
                "SEC_HEADER_HSTS",
                "max-age=63072000; includeSubDomains; preload",
            ),
        )
        headers.setdefault("x-content-type-options", "nosniff")

        # Clickjacking / framing.
        headers.setdefault("x-frame-options", "DENY")

        # Privacy / cross-tab isolation.
        headers.setdefault("referrer-policy", "strict-origin-when-cross-origin")
        headers.setdefault("cross-origin-opener-policy", "same-origin")
        headers.setdefault("cross-origin-resource-policy", "same-origin")

        # CSP — overridable for apps that legitimately need extra sources.
        headers.setdefault(
            "content-security-policy",
            _default("SEC_HEADER_CSP", _DEFAULT_CSP),
        )

        # Strip stack fingerprints. Some proxies re-add Server; clients
        # only see the last value so our override wins downstream of us.
        for leak in ("server", "x-powered-by"):
            if leak in headers:
                del headers[leak]

        return response
