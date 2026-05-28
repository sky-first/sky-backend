"""Redis configuration and connection management."""

import logging
from typing import Optional

import redis.asyncio as aioredis
from redis.asyncio import Redis

from src.config.settings import settings

logger = logging.getLogger(__name__)

# Global Redis connection pool
_redis: Optional[Redis] = None


async def get_redis() -> Redis:
    """
    Get Redis connection.

    Returns:
        Redis: Redis client instance
    """
    if _redis is None:
        await init_redis()
    return _redis


async def init_redis() -> None:
    """Initialize Redis connection."""
    global _redis

    # Strategy: Try atomic variables first (Host/Port) as they are more robust in Kubernetes
    # and avoid manual parsing of complex URLs with special characters.
    if settings.REDIS_HOST and settings.REDIS_HOST != "localhost":
        try:
            logger.info(
                f"Connecting to Redis via atomic vars: host={settings.REDIS_HOST}, port={settings.REDIS_PORT}"
            )
            _redis = Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                password=settings.REDIS_PASSWORD or None,
                encoding="utf-8",
                decode_responses=True,
                max_connections=50,
            )
            # Verify connection
            await _redis.ping()
            return
        except Exception as e:
            logger.warning(
                f"Failed to connect to Redis via atomic vars, falling back to URL parsing: {e}"
            )
            _redis = None

    # Fallback/Default: Parse Redis URL manually to handle special characters in password
    redis_url = settings.REDIS_URL or "redis://localhost:6379/0"

    # Extract components from URL
    # Format: redis://:password@host:port/db or redis://username:password@host:port/db
    try:
        # Try to parse the URL
        if redis_url.startswith("redis://"):
            url_part = redis_url[8:]  # Remove "redis://"

            # Check if password is present (look for @ which indicates auth)
            # Only parse manually if there's actually authentication info
            if "@" in url_part:
                auth_part, host_part = url_part.split("@", 1)

                # Extract password (may be after : or just password)
                # Format: redis://:password@host or redis://user:password@host
                has_password = False
                if auth_part.startswith(":"):
                    # Format: redis://:password@host (password only, no username)
                    username = None
                    password = auth_part[1:] if len(auth_part) > 1 else None
                    has_password = bool(password)
                elif ":" in auth_part:
                    # Format: redis://user:password@host
                    username, password = auth_part.split(":", 1)
                    has_password = bool(password)
                else:
                    # No password, just username or empty
                    username = auth_part if auth_part else None
                    password = None
                    has_password = False

                # If no actual password, use from_url instead (simpler)
                if not has_password:
                    _redis = await aioredis.from_url(
                        redis_url,
                        encoding="utf-8",
                        decode_responses=True,
                        max_connections=50,
                    )
                    return

                # Extract host and port
                if ":" in host_part:
                    host, port_db = host_part.split(":", 1)
                    if "/" in port_db:
                        port, db = port_db.split("/", 1)
                    else:
                        port = port_db
                        db = "0"
                else:
                    if "/" in host_part:
                        host, db = host_part.split("/", 1)
                    else:
                        host = host_part
                        db = "0"
                    port = "6379"

                # Only pass password/username if they are actually provided (not empty strings)
                connection_kwargs = {
                    "host": host,
                    "port": int(port),
                    "db": int(db) if db else 0,
                    "encoding": "utf-8",
                    "decode_responses": True,
                    "max_connections": 50,
                }

                # Only add password if it's not None and not empty
                if password:
                    connection_kwargs["password"] = password
                # Only add username if it's not None and not empty
                if username:
                    connection_kwargs["username"] = username

                # Create connection using Redis constructor directly
                _redis = Redis(**connection_kwargs)
            else:
                # No password, use from_url
                _redis = await aioredis.from_url(
                    redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    max_connections=50,
                )
        else:
            # Fallback to from_url
            _redis = await aioredis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                max_connections=50,
            )
    except Exception as e:
        # If connection fails, log error but don't fail startup (OK for local development)
        logger.error(
            f"Failed to connect to Redis: {e}. Continuing without Redis (OK for local development)"
        )
        _redis = None


async def close_redis() -> None:
    """Close Redis connection."""
    global _redis
    if _redis:
        try:
            await _redis.aclose()
        except Exception:
            pass
        _redis = None
