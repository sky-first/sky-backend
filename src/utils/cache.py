"""Cache utilities using Redis."""

import hashlib
import json
import re
from typing import Any, Optional, TypeVar

from src.config.redis import get_redis

T = TypeVar("T")


class CacheService:
    """Cache service using Redis."""

    @staticmethod
    async def get(key: str) -> Optional[str]:
        """
        Get value from cache.

        Args:
            key: Cache key

        Returns:
            Optional[str]: Cached value or None
        """
        redis = await get_redis()
        return await redis.get(key)

    @staticmethod
    async def set(key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        Set value in cache.

        Args:
            key: Cache key
            value: Value to cache (will be JSON serialized if not string)
            ttl: Time to live in seconds
        """
        redis = await get_redis()
        if isinstance(value, str):
            await redis.set(key, value, ex=ttl)
        else:
            await redis.set(key, json.dumps(value), ex=ttl)

    @staticmethod
    async def delete(key: str) -> None:
        """
        Delete key from cache.

        Args:
            key: Cache key
        """
        redis = await get_redis()
        await redis.delete(key)

    @staticmethod
    async def delete_pattern(pattern: str) -> int:
        """
        Delete keys matching pattern.

        Args:
            pattern: Redis key pattern (e.g., "widget:*")

        Returns:
            int: Number of keys deleted
        """
        redis = await get_redis()
        keys = await redis.keys(pattern)
        if keys:
            return await redis.delete(*keys)
        return 0

    @staticmethod
    async def get_json(key: str) -> Optional[Any]:
        """
        Get JSON value from cache.

        Args:
            key: Cache key

        Returns:
            Optional[Any]: Parsed JSON value or None
        """
        value = await CacheService.get(key)
        if value:
            return json.loads(value)
        return None

    @staticmethod
    async def set_json(key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        Set JSON value in cache.

        Args:
            key: Cache key
            value: Value to cache (will be JSON serialized)
            ttl: Time to live in seconds
        """
        await CacheService.set(key, json.dumps(value), ttl=ttl)


# Cache key generators
def widget_cache_key(widget_id: str) -> str:
    """Generate cache key for widget."""
    return f"widget:{widget_id}"


def page_cache_key(dashboard_id: str) -> str:
    """Generate cache key for dashboard."""
    return f"dashboard:{dashboard_id}"


def workspace_cache_key(workspace_id: str) -> str:
    """Generate cache key for workspace."""
    return f"workspace:{workspace_id}"


def connection_metadata_cache_key(connection_id: str) -> str:
    """Generate cache key for connection metadata."""
    return f"connection:metadata:{connection_id}"


def _normalize_question(question: str) -> str:
    """Normalize user question for stable cache keys."""
    q = (question or "").strip().lower()
    q = re.sub(r"\s+", " ", q)
    return q


def ai_response_cache_key(space_id: str, connection_id: str, question: str) -> str:
    """
    Generate cache key for AI response.

    Key = sha256(space_id + connection_id + normalized_question)
    """
    normalized = _normalize_question(question)
    raw = f"{space_id}|{connection_id}|{normalized}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"ai:resp:v1:{digest}"
