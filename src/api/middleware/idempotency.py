"""Idempotency middleware using Redis to prevent duplicate processing of mutations."""

import json
import logging
from typing import Any, Callable, cast

from fastapi import Request, Response
from starlette.concurrency import iterate_in_threadpool

from src.config.redis import get_redis
from src.config.settings import settings

logger = logging.getLogger(__name__)


async def idempotency_middleware(request: Request, call_next: Callable) -> Response:
    """
    Idempotency middleware.

    Checks for 'Idempotency-Key' header in mutations (POST, PUT, PATCH, DELETE).
    If found, checks Redis for a cached response for that key + user_id.
    """
    idempotency_key = request.headers.get("Idempotency-Key")

    # Only apply to mutations and if header is present
    if not idempotency_key or request.method == "GET":
        return cast(Response, await call_next(request))

    try:
        redis = await get_redis()
        if redis is None:
            # Redis not available, skip idempotency
            logger.debug("Redis not available, skipping idempotency")
            return cast(Response, await call_next(request))

        # User ID should be set by auth_middleware which executes BEFORE this
        user_id = (
            getattr(request.state, "user_id", None)
            if hasattr(request.state, "user_id")
            else "anonymous"
        )

        # Unique key per user + idempotency key
        redis_key = f"idempotency:{user_id}:{idempotency_key}"

        # 1. Check if we have a cached response
        cached_data = await redis.get(redis_key)
        if cached_data:
            logger.info(f"Idempotency HIT for key: {idempotency_key}, user: {user_id}")
            try:
                data = json.loads(cached_data)

                # Reconstruct headers without breaking Starlette's response logic
                # We skip certain hop-by-hop headers if they were cached
                skip_headers = {"content-length", "connection", "keep-alive"}
                resp_headers = {
                    k: v for k, v in data["headers"].items() if k.lower() not in skip_headers
                }
                resp_headers["X-Idempotency-Cache"] = "HIT"

                return Response(
                    content=data["body"],
                    status_code=data["status_code"],
                    headers=resp_headers,
                    media_type=data.get("media_type", "application/json"),
                )
            except Exception as e:
                logger.warning(
                    f"Failed to parse cached idempotency data for key {idempotency_key}: {e}"
                )

        # 2. Process request normally if no cache hit
        response = cast(Response, await call_next(request))

        # 3. Cache successful (2xx) responses
        if 200 <= response.status_code < 300:
            logger.debug(f"Caching successful response for idempotency key: {idempotency_key}")

            # Read body from iterator
            # We use Any cast because body_iterator is not in base Response but present in StreamingResponse
            res_any = cast(Any, response)
            response_body = [section async for section in res_any.body_iterator]
            # Restore body iterator so background processing/FastAPI can still use it
            res_any.body_iterator = iterate_in_threadpool(iter(response_body))

            # Combine body parts
            full_body_bytes = b"".join(response_body)
            # Try to store as string if possible, or base64 if binary?
            # Most of our responses are JSON (text).
            try:
                full_body = full_body_bytes.decode("utf-8")
            except UnicodeDecodeError:
                # If binary, we might not want to cache it or we'd need base64
                # For now, we only care about API JSON mutations
                return response

            # Prepare metadata for caching
            cache_payload = {
                "status_code": response.status_code,
                "body": full_body,
                "headers": dict(response.headers),
                "media_type": response.media_type,
            }

            await redis.setex(
                redis_key, settings.IDEMPOTENCY_TTL_SECONDS, json.dumps(cache_payload)
            )

        return response

    except Exception as e:
        logger.error(f"Idempotency middleware error (continuing without idempotency): {str(e)}")
        # On middleware internal failure, allow request to proceed
        return cast(Response, await call_next(request))
