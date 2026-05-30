"""Rate limiting middleware."""

import logging
from typing import Callable, cast

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse

from src.config.redis import get_redis
from src.config.settings import settings

logger = logging.getLogger(__name__)


async def rate_limit_middleware(request: Request, call_next: Callable) -> Response:
    """
    Rate limiting middleware.

    Args:
        request: FastAPI request
        call_next: Next middleware/route handler

    Returns:
        Response: HTTP response
    """
    if not settings.RATE_LIMIT_ENABLED:
        return cast(Response, await call_next(request))

    # Skip rate limiting for CORS preflight requests
    if request.method == "OPTIONS":
        return cast(Response, await call_next(request))

    # Skip rate limiting for health checks (both legacy and k8s-style)
    if request.url.path in [
        "/health",
        "/healthz",
        "/healthz/ready",
        "/healthz/live",
        "/ready",
        "/live",
        "/metrics",
    ]:
        return cast(Response, await call_next(request))

    # Skip rate limiting for low-cost polling/status endpoints (frontend may poll frequently).
    # Also skip for auth endpoints to prevent login issues (auth has its own protections or higher needs).
    path = getattr(getattr(request, "url", None), "path", "") or ""
    if isinstance(path, str):
        if path.startswith("/api/v1/dashboards/ai/build-jobs/"):
            return cast(Response, await call_next(request))
        if "/auth/" in path:
            return cast(Response, await call_next(request))

    # Track whether we've started the downstream call — critical because
    # ASGI consumes the receive channel on the first call_next and a
    # retry will deadlock the request.
    response: Response | None = None
    try:
        redis = await get_redis()
        if redis is None:
            # Redis not available, skip rate limiting
            logger.debug("Redis not available, skipping rate limiting")
            response = cast(Response, await call_next(request))
            return response

        # Try to get real IP if behind a proxy
        client_ip = request.headers.get("X-Forwarded-For")
        if client_ip:
            client_ip = client_ip.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"

        user_id = (
            getattr(request.state, "user_id", None) if hasattr(request.state, "user_id") else None
        )

        # Use user_id if available, otherwise use IP
        identifier = f"user:{user_id}" if user_id else f"ip:{client_ip}"

        # Console gets its own bucket (Gap #2 from the 2026-05-30
        # security posture audit). /api/console/v1/* is a low-volume
        # operator surface; budget separately so a runaway tenant
        # request burst can't burn the Console quota, and a Console
        # script gone wild can't drain the customer-facing quota.
        # Prefix splits the Redis keyspace; the limits read from
        # CONSOLE_RATE_LIMIT_* settings.
        path_str = path if isinstance(path, str) else ""
        is_console = path_str.startswith("/api/console/v1") or path_str.startswith("/api/console")
        bucket_prefix = "rate_limit:console" if is_console else "rate_limit"
        minute_limit = (
            settings.CONSOLE_RATE_LIMIT_PER_MINUTE if is_console else settings.RATE_LIMIT_PER_MINUTE
        )
        hour_limit = (
            settings.CONSOLE_RATE_LIMIT_PER_HOUR if is_console else settings.RATE_LIMIT_PER_HOUR
        )

        # Per-minute limit
        minute_key = f"{bucket_prefix}:minute:{identifier}"
        minute_count = await redis.incr(minute_key)
        if minute_count == 1:
            await redis.expire(minute_key, 60)
        if minute_count > minute_limit:
            logger.warning(f"Rate limit exceeded (minute) bucket={bucket_prefix}: {identifier}")
            response = JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Too Many Requests",
                    "message": (
                        f"Console rate limit exceeded ({minute_limit}/min). Please slow down."
                        if is_console
                        else "Rate limit exceeded. Please try again later."
                    ),
                },
                headers={"Retry-After": "60"},
            )
            origin = request.headers.get("Origin")
            if origin and origin in settings.cors_origins_list:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers.add_vary_header("Origin")
            return response

        # Per-hour limit
        hour_key = f"{bucket_prefix}:hour:{identifier}"
        hour_count = await redis.incr(hour_key)
        if hour_count == 1:
            await redis.expire(hour_key, 3600)
        if hour_count > hour_limit:
            logger.warning(f"Rate limit exceeded (hour) bucket={bucket_prefix}: {identifier}")
            response = JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Too Many Requests",
                    "message": "Hourly rate limit exceeded. Please try again later.",
                },
                headers={"Retry-After": "3600"},
            )
            origin = request.headers.get("Origin")
            if origin and origin in settings.cors_origins_list:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers.add_vary_header("Origin")
            return response

        response = await call_next(request)

        # Add rate limit headers — skip if response is already finalized
        # (StreamingResponse may lock headers after starting the body).
        response.headers["X-RateLimit-Limit-Minute"] = str(minute_limit)
        response.headers["X-RateLimit-Remaining-Minute"] = str(
            max(0, minute_limit - minute_count)
        )
        response.headers["X-RateLimit-Limit-Hour"] = str(hour_limit)
        response.headers["X-RateLimit-Remaining-Hour"] = str(
            max(0, hour_limit - hour_count)
        )
        if is_console:
            response.headers["X-RateLimit-Bucket"] = "console"

        return response
    except Exception as e:
        logger.warning(f"Rate limiting error (continuing without rate limit): {str(e)}")
        # ASGI consumes the receive channel on the first call_next, so
        # we must never call it twice on the same request. Three cases:
        #   1) Failure BEFORE call_next started (response is None): we
        #      safely invoke it once, skipping rate-limit work.
        #   2) Failure AFTER call_next produced a response (e.g. header
        #      mutation threw): return the response as-is.
        #   3) Failure INSIDE call_next itself: exception bubbled from
        #      the app — surface a 500 rather than hang.
        if response is not None:
            return response
        try:
            return cast(Response, await call_next(request))
        except Exception:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"error": "Internal Server Error", "message": "Request failed"},
            )
