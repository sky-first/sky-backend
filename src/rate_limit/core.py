"""Core building blocks for tenant/user rate limiting.

Subtask 1 delivers:
- tenant_key resolution (crew_id based + fallback)
- Redis fixed-window counters (minute/hour etc) with Retry-After + reset_at
- a canonical 429 exception payload (to be used by endpoints/workers in later subtasks)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Literal, Optional, Sequence

from fastapi import HTTPException, status

from src.config.redis import get_redis

TenantKeyKind = Literal["crew", "space", "personal", "user"]


def resolve_tenant_key(
    *,
    user_id: str,
    crew_ids: Optional[Sequence[str]] = None,
    space_id: Optional[str] = None,
    is_personal: bool = False,
) -> str:
    """Resolve a stable tenant key for rate limiting.

    Rules (deterministic):
    - If exactly 1 crew_id is present -> crew:{crew_id}
    - If multiple crews:
        - if space_id exists -> space:{space_id}
        - else -> personal:{user_id}
    - If no crews:
        - if is_personal -> personal:{user_id}
        - elif space_id exists -> space:{space_id}
        - else -> user:{user_id}
    """

    crews = [c for c in (crew_ids or []) if c]
    if len(crews) == 1:
        return f"crew:{crews[0]}"
    if len(crews) > 1:
        return f"space:{space_id}" if space_id else f"personal:{user_id}"
    if is_personal:
        return f"personal:{user_id}"
    if space_id:
        return f"space:{space_id}"
    return f"user:{user_id}"


@dataclass(frozen=True)
class Bucket:
    """A single fixed-window bucket to enforce."""

    key: str
    limit: int
    window_seconds: int
    scope: Literal["tenant", "user", "global_user"]


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    key: str
    scope: str
    limit: int
    remaining: int
    reset_at: str
    retry_after_seconds: int
    window_seconds: int
    current: int

    def to_headers(self) -> Dict[str, str]:
        return {"Retry-After": str(max(0, int(self.retry_after_seconds)))}

    def to_payload(self) -> Dict[str, Any]:
        return {
            "error": "rate_limited",
            "message": "Rate limit exceeded. Please try again later.",
            "scope": self.scope,
            "key": self.key,
            "limit": int(self.limit),
            "remaining": int(self.remaining),
            "reset_at": self.reset_at,
            "window_seconds": int(self.window_seconds),
        }


class RateLimitExceeded(Exception):
    def __init__(self, result: RateLimitResult):
        super().__init__("rate_limited")
        self.result = result

    def to_http_exception(self) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=self.result.to_payload(),
            headers=self.result.to_headers(),
        )


class RedisFixedWindowRateLimiter:
    """Redis-backed fixed window limiter (INCR + EXPIRE) using a Lua helper for atomicity."""

    _LUA_INCR_EXPIRE_TTL = """
local v = redis.call('INCR', KEYS[1])
if v == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {v, ttl}
"""

    def __init__(self, *, enabled: bool = True, key_prefix: str = "rl:v1"):
        self.enabled = enabled
        self.key_prefix = key_prefix

    def build_bucket_key(
        self,
        *,
        tenant_key: str,
        user_id: str,
        route_key: str,
        scope: Literal["tenant", "user", "global_user"],
        window: Literal["min", "hour"],
    ) -> str:
        # NOTE: keep keys stable + debuggable
        if scope == "tenant":
            return f"{self.key_prefix}:tenant:{tenant_key}:route:{route_key}:{window}"
        if scope == "user":
            return f"{self.key_prefix}:tenant:{tenant_key}:user:{user_id}:route:{route_key}:{window}"
        # global_user
        return f"{self.key_prefix}:global:user:{user_id}:route:{route_key}:{window}"

    async def hit(self, bucket: Bucket) -> RateLimitResult:
        """Increment a bucket and return remaining/reset metadata."""

        if not self.enabled:
            now = datetime.now(timezone.utc)
            return RateLimitResult(
                allowed=True,
                key=bucket.key,
                scope=bucket.scope,
                limit=bucket.limit,
                remaining=bucket.limit,
                reset_at=(now + timedelta(seconds=bucket.window_seconds)).isoformat(),
                retry_after_seconds=0,
                window_seconds=bucket.window_seconds,
                current=0,
            )

        redis = await get_redis()
        if redis is None:
            # Redis unavailable: allow (cost protection must be best-effort in local dev)
            now = datetime.now(timezone.utc)
            return RateLimitResult(
                allowed=True,
                key=bucket.key,
                scope=bucket.scope,
                limit=bucket.limit,
                remaining=bucket.limit,
                reset_at=(now + timedelta(seconds=bucket.window_seconds)).isoformat(),
                retry_after_seconds=0,
                window_seconds=bucket.window_seconds,
                current=0,
            )

        # Atomic INCR + conditional EXPIRE + TTL
        current, ttl = await redis.eval(  # type: ignore[no-untyped-call]
            self._LUA_INCR_EXPIRE_TTL,  # noqa: S608 (Redis script)
            1,
            bucket.key,
            int(bucket.window_seconds),
        )

        ttl_int = (
            int(ttl) if ttl is not None and int(ttl) >= 0 else bucket.window_seconds
        )
        now = datetime.now(timezone.utc)
        reset_at = (now + timedelta(seconds=ttl_int)).isoformat()
        remaining = max(0, int(bucket.limit) - int(current))
        allowed = int(current) <= int(bucket.limit)

        return RateLimitResult(
            allowed=allowed,
            key=bucket.key,
            scope=bucket.scope,
            limit=int(bucket.limit),
            remaining=remaining,
            reset_at=reset_at,
            retry_after_seconds=ttl_int,
            window_seconds=int(bucket.window_seconds),
            current=int(current),
        )

    async def enforce(self, buckets: Iterable[Bucket]) -> None:
        """Enforce multiple buckets; raises RateLimitExceeded on first violation."""

        for b in buckets:
            res = await self.hit(b)
            if not res.allowed:
                raise RateLimitExceeded(res)


def default_buckets_for_request(
    *,
    tenant_key: str,
    user_id: str,
    route_key: str,
    user_per_min: int,
    user_per_hour: int,
    tenant_per_min: int,
    tenant_per_hour: int,
    global_user_per_hour: int,
    key_prefix: str = "rl:v1",
) -> list[Bucket]:
    """Convenience helper: build the 5 buckets we agreed on (user+tenant+hardcap)."""

    limiter = RedisFixedWindowRateLimiter(key_prefix=key_prefix)
    return [
        Bucket(
            key=limiter.build_bucket_key(
                tenant_key=tenant_key,
                user_id=user_id,
                route_key=route_key,
                scope="user",
                window="min",
            ),
            limit=user_per_min,
            window_seconds=60,
            scope="user",
        ),
        Bucket(
            key=limiter.build_bucket_key(
                tenant_key=tenant_key,
                user_id=user_id,
                route_key=route_key,
                scope="user",
                window="hour",
            ),
            limit=user_per_hour,
            window_seconds=3600,
            scope="user",
        ),
        Bucket(
            key=limiter.build_bucket_key(
                tenant_key=tenant_key,
                user_id=user_id,
                route_key=route_key,
                scope="tenant",
                window="min",
            ),
            limit=tenant_per_min,
            window_seconds=60,
            scope="tenant",
        ),
        Bucket(
            key=limiter.build_bucket_key(
                tenant_key=tenant_key,
                user_id=user_id,
                route_key=route_key,
                scope="tenant",
                window="hour",
            ),
            limit=tenant_per_hour,
            window_seconds=3600,
            scope="tenant",
        ),
        Bucket(
            key=limiter.build_bucket_key(
                tenant_key=tenant_key,
                user_id=user_id,
                route_key=route_key,
                scope="global_user",
                window="hour",
            ),
            limit=global_user_per_hour,
            window_seconds=3600,
            scope="global_user",
        ),
    ]
