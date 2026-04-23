"""Regression for the token-revocation on logout fix.

Red-team HI (2026-04-23): /auth/logout deleted only the refresh
token; the access token kept working until its 15-min exp. An
attacker with a leaked access token could keep operating through
a logout.

Fix: core/token_blocklist.py writes a per-user ``revoke_before``
marker in Redis on logout; auth middleware rejects tokens whose
``iat`` predates it. These tests exercise the helper itself (the
E2E middleware flow is covered by the red-team suite).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_is_token_revoked_returns_true_when_iat_is_older():
    uid = str(uuid4())

    class _Fake:
        async def get(self, _k):
            return "1000000000"  # a big epoch
        async def setex(self, _k, _ttl, _v):
            return True

    with patch("src.core.token_blocklist._client", return_value=_Fake()):
        from src.core.token_blocklist import is_token_revoked
        assert await is_token_revoked(uid, token_iat=999999999) is True


@pytest.mark.asyncio
async def test_is_token_revoked_returns_false_when_iat_is_newer():
    uid = str(uuid4())

    class _Fake:
        async def get(self, _k):
            return "1000000000"

    with patch("src.core.token_blocklist._client", return_value=_Fake()):
        from src.core.token_blocklist import is_token_revoked
        assert await is_token_revoked(uid, token_iat=1000000001) is False


@pytest.mark.asyncio
async def test_is_token_revoked_returns_false_when_no_marker():
    uid = str(uuid4())

    class _Fake:
        async def get(self, _k):
            return None

    with patch("src.core.token_blocklist._client", return_value=_Fake()):
        from src.core.token_blocklist import is_token_revoked
        assert await is_token_revoked(uid, token_iat=123) is False


@pytest.mark.asyncio
async def test_is_token_revoked_fails_open_on_redis_error():
    """If Redis is unreachable, we treat the token as NOT revoked (log
    + continue). Trade-off: instant-logout is degraded but normal
    sessions keep working."""
    class _Fake:
        async def get(self, _k):
            raise RuntimeError("redis down")

    with patch("src.core.token_blocklist._client", return_value=_Fake()):
        from src.core.token_blocklist import is_token_revoked
        assert await is_token_revoked(str(uuid4()), token_iat=123) is False


@pytest.mark.asyncio
async def test_revoke_and_check_round_trip():
    """Simulate the E2E path: revoke_user_tokens then is_token_revoked
    reads back the same marker. Uses the in-memory Fake as Redis."""
    state = {}

    class _Fake:
        async def get(self, k):
            return state.get(k)
        async def setex(self, k, _ttl, v):
            state[k] = v

    fake = _Fake()
    with patch("src.core.token_blocklist._client", return_value=fake):
        from src.core.token_blocklist import (
            is_token_revoked,
            revoke_user_tokens,
        )
        uid = str(uuid4())
        await revoke_user_tokens(uid, issued_before_epoch=1_700_000_000)
        # Token issued AFTER revoke → fine.
        assert await is_token_revoked(uid, token_iat=1_700_000_001) is False
        # Token issued BEFORE revoke → blocked.
        assert await is_token_revoked(uid, token_iat=1_699_999_999) is True


def test_access_token_carries_iat():
    """create_access_token must now embed an `iat` so the blocklist
    has something to compare against."""
    from src.core.security import create_access_token
    from jose import jwt as _jwt

    tok = create_access_token({"sub": "00000000-0000-0000-0000-000000000001"})
    claims = _jwt.get_unverified_claims(tok)
    assert "iat" in claims
    assert int(claims["iat"]) > 0
