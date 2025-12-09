"""Redis configuration and connection management."""

import logging
import redis.asyncio as aioredis
from redis.asyncio import Redis

from src.config.settings import settings

logger = logging.getLogger(__name__)

# Global Redis connection pool
_redis: Redis | None = None


async def get_redis() -> Redis:
    """
    Get Redis connection.

    Returns:
        Redis: Redis client instance
    """
    global _redis
    if _redis is None:
        await init_redis()
    return _redis


async def init_redis() -> None:
    """Initialize Redis connection."""
    global _redis
    from urllib.parse import urlparse
    
    # Parse Redis URL manually to handle special characters in password
    redis_url = settings.REDIS_URL
    
    # Extract components from URL
    # Format: redis://:password@host:port/db or redis://username:password@host:port/db
    try:
        # Try to parse the URL
        if redis_url.startswith("redis://"):
            url_part = redis_url[8:]  # Remove "redis://"
            
            # Check if password is present
            if "@" in url_part:
                auth_part, host_part = url_part.split("@", 1)
                
                # Extract password (may be after : or just password)
                # Format: redis://:password@host or redis://user:password@host
                if auth_part.startswith(":"):
                    # Format: redis://:password@host (password only, no username)
                    username = None
                    password = auth_part[1:] if len(auth_part) > 1 else None
                elif ":" in auth_part:
                    # Format: redis://user:password@host
                    username, password = auth_part.split(":", 1)
                else:
                    # No password, just username
                    username = auth_part if auth_part else None
                    password = None
                
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
                
                # Create connection using Redis constructor directly
                _redis = Redis(
                    host=host,
                    port=int(port),
                    db=int(db) if db else 0,
                    password=password if password else None,
                    username=username if username else None,
                    encoding="utf-8",
                    decode_responses=True,
                    max_connections=50,
                )
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
        logger.error(f"Failed to connect to Redis: {e}. Continuing without Redis (OK for local development)")
        _redis = None


async def close_redis() -> None:
    """Close Redis connection."""
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
