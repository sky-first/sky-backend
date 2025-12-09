"""Rate limiting middleware."""

import logging
from typing import Callable

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
        return await call_next(request)

    # Skip rate limiting for health checks
    if request.url.path in ["/health", "/ready", "/live", "/metrics"]:
        return await call_next(request)

    try:
        redis = await get_redis()
        client_ip = request.client.host if request.client else "unknown"
        user_id = getattr(request.state, "user_id", None) if hasattr(request.state, "user_id") else None

        # Use user_id if available, otherwise use IP
        identifier = f"user:{user_id}" if user_id else f"ip:{client_ip}"

        # Per-minute limit
        minute_key = f"rate_limit:minute:{identifier}"
        minute_count = await redis.incr(minute_key)
        if minute_count == 1:
            await redis.expire(minute_key, 60)
        if minute_count > settings.RATE_LIMIT_PER_MINUTE:
            logger.warning(f"Rate limit exceeded (minute): {identifier}")
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Too Many Requests",
                    "message": "Rate limit exceeded. Please try again later.",
                },
                headers={"Retry-After": "60"},
            )

        # Per-hour limit
        hour_key = f"rate_limit:hour:{identifier}"
        hour_count = await redis.incr(hour_key)
        if hour_count == 1:
            await redis.expire(hour_key, 3600)
        if hour_count > settings.RATE_LIMIT_PER_HOUR:
            logger.warning(f"Rate limit exceeded (hour): {identifier}")
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Too Many Requests",
                    "message": "Hourly rate limit exceeded. Please try again later.",
                },
                headers={"Retry-After": "3600"},
            )

        response = await call_next(request)

        # Add rate limit headers
        response.headers["X-RateLimit-Limit-Minute"] = str(settings.RATE_LIMIT_PER_MINUTE)
        response.headers["X-RateLimit-Remaining-Minute"] = str(
            max(0, settings.RATE_LIMIT_PER_MINUTE - minute_count)
        )
        response.headers["X-RateLimit-Limit-Hour"] = str(settings.RATE_LIMIT_PER_HOUR)
        response.headers["X-RateLimit-Remaining-Hour"] = str(
            max(0, settings.RATE_LIMIT_PER_HOUR - hour_count)
        )

        return response
    except Exception as e:
        logger.error(f"Rate limiting error: {str(e)}")
        # On error, allow request to proceed
        return await call_next(request)

