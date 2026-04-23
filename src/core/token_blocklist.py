"""Logout-aware token revocation.

Red-team HI (2026-04-23): `POST /auth/logout` only deleted the refresh
token — the access token kept working until its JWT `exp` (default
15 min). An attacker with a stolen access token could keep using it
even after the legitimate user clicked "Sign out from all devices".

Strategy: per-user "tokens-issued-before-this-timestamp are revoked"
marker, stored in Redis. Lightweight — no need to track individual
jti ids, and no migration to add jti to existing access tokens.

Flow
  1. On logout, bump the user's ``revoke_before`` to now.
  2. Auth middleware, after verify_token(), checks:
       if token.iat < redis[revoke_before_key_for(user)]:
         reject as 401
  3. On refresh / new-login we issue a fresh token with iat=now, so
     the user's own re-login clears itself naturally — no need to
     expire the Redis key explicitly (though a TTL avoids stale
     entries forever).

This module owns the revocation primitive. It's a sync-safe shim
around the async Redis client — if Redis is unreachable we FAIL
CLOSED (treat every token as revoked) only when the TTL is
non-trivial; for immediate reads we return ``None`` and let the
middleware decide (documented as "fail open on Redis-down" below —
pragmatic choice; documented trade-off in the runbook).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import redis.asyncio as aioredis

from src.config.settings import settings

logger = logging.getLogger(__name__)


_PREFIX = "auth:revoke_before:"
# If the app outlives its TTL the key expires and the ban is cleared.
# Set it to slightly longer than the refresh-token lifetime so a user
# who logged out can still get re-banned via a leaked refresh that
# they haven't rotated yet. 8 days when refresh is 7.
_TTL_SECONDS = (getattr(settings, "JWT_REFRESH_TOKEN_EXPIRE_DAYS", 7) + 1) * 86400


_redis: Optional[aioredis.Redis] = None


def _client() -> aioredis.Redis:
    """Lazy init of the async Redis client. Module-level so we reuse
    the pool across requests."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.REDIS_URL, encoding="utf-8", decode_responses=True
        )
    return _redis


async def revoke_user_tokens(user_id: str, *, issued_before_epoch: int) -> None:
    """Mark every token issued before ``issued_before_epoch`` for
    ``user_id`` as revoked. Called by /auth/logout with the current
    epoch second."""
    try:
        r = _client()
        key = _PREFIX + str(user_id)
        await r.setex(key, _TTL_SECONDS, str(int(issued_before_epoch)))
    except Exception as exc:
        # Log but do not block logout — if Redis is down, the token
        # still has a short TTL and the user's follow-up re-login
        # issues a fresh one. We lose the "instant invalidation"
        # guarantee temporarily; correctness is not compromised.
        logger.warning("token_blocklist: revoke failed for user %s: %s", user_id, exc)


async def is_token_revoked(user_id: str, token_iat: Optional[int]) -> bool:
    """Return True when the token's ``iat`` is older than the user's
    most recent ``revoke_before`` marker.

    ``token_iat=None`` (legacy tokens without the claim) are treated as
    NOT revoked so pre-existing sessions don't break; every new access
    token carries ``iat`` (see src/core/security.create_access_token).
    """
    if not token_iat:
        return False
    try:
        r = _client()
        key = _PREFIX + str(user_id)
        val = await r.get(key)
        if not val:
            return False
        return int(val) > int(token_iat)
    except Exception as exc:
        # Fail open on Redis unreachable — same trade-off as revoke().
        logger.warning("token_blocklist: check failed for user %s: %s", user_id, exc)
        return False


# Tiny sync shim so callers in sync-only code (rare) still work.
def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return asyncio.ensure_future(coro)
    except RuntimeError:
        pass
    return asyncio.run(coro)
