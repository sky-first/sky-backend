"""Request-level DoS mitigations.

Red-team (dos 2026-04-23): the app accepted a 5 MB chat message and
a 2000-level nested JSON payload. Both are cheap DoS vectors — the
chat message hits the LLM path (expensive) with zero limit; the
nested JSON can exhaust Python's json.loads recursion.

Two complementary guards:

1. ``Content-Length`` check at request entry — rejects anything over
   ``MAX_REQUEST_BODY_BYTES`` (default 1 MiB) with 413 Payload Too
   Large before the body is read into memory. JSON bodies rarely
   need to be this big; file uploads go through a separate route with
   its own policy.

2. ``deep_json_sanity`` helper — called from FastAPI dependency or
   endpoint when the body structure is expected to be shallow. Rejects
   payloads nested more than ``MAX_JSON_DEPTH`` (default 32) levels.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from fastapi import HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


MAX_REQUEST_BODY_BYTES = _int_env("MAX_REQUEST_BODY_BYTES", 1 * 1024 * 1024)  # 1 MiB
MAX_JSON_DEPTH = _int_env("MAX_JSON_DEPTH", 32)


# Routes that legitimately accept larger bodies (e.g. CSV upload).
# Check by path prefix; keep short — any new large-body endpoint should
# declare itself here AND justify the size in code review.
_LARGE_BODY_ALLOWLIST: tuple[str, ...] = (
    "/api/v1/file-upload",
    "/api/v1/ingest",
)


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length = int(content_length)
            except ValueError:
                length = None
            if length is not None:
                path = request.url.path
                if length > MAX_REQUEST_BODY_BYTES and not any(
                    path.startswith(p) for p in _LARGE_BODY_ALLOWLIST
                ):
                    return JSONResponse(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        content={
                            "error": {
                                "code": "PAYLOAD_TOO_LARGE",
                                "message": (
                                    f"Body of {length} bytes exceeds limit "
                                    f"{MAX_REQUEST_BODY_BYTES} for this route."
                                ),
                            }
                        },
                    )
        return await call_next(request)


def _depth(obj: Any, current: int = 0, limit: int = MAX_JSON_DEPTH) -> int:
    """Return the maximum nesting depth of ``obj``. Bails out once the
    limit is exceeded so a billion-laughs-style payload doesn't melt
    the checker itself."""
    if current > limit:
        return current
    if isinstance(obj, dict):
        return max(
            (_depth(v, current + 1, limit) for v in obj.values()),
            default=current,
        )
    if isinstance(obj, list):
        return max(
            (_depth(v, current + 1, limit) for v in obj),
            default=current,
        )
    return current


def reject_deep_json_or_400(body: Any, limit: int = MAX_JSON_DEPTH) -> None:
    """Raise 400 when body exceeds the nesting cap."""
    if _depth(body, limit=limit) > limit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"JSON body nested deeper than {limit} — rejected.",
        )
