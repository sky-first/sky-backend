"""BE-05 · Mobile auth-hardening gap closure (G5).

Covers the masterplan acceptance rows the earlier BE-05 pass left open:
T-05.1 (mobile refresh TTL), T-05.7 (per-device revocation) and T-05.8
(tid-mismatch on refresh). Reuse/family behaviour (T-05.2) lives in
test_refresh_token_reuse.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.config.settings import settings
from src.core.exceptions import UnauthorizedError
from src.core.security import create_refresh_token, verify_token
from src.core.tenant_context import TenantContext, reset_current_tenant, set_current_tenant
from src.models.user import RefreshToken
from src.services.auth_service import AuthenticationService


async def _refresh_row(db, token: str) -> RefreshToken:
    res = await db.execute(select(RefreshToken).where(RefreshToken.token == token))
    return res.scalar_one_or_none()


def _days_until(expires_at) -> float:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return (expires_at - datetime.now(timezone.utc)).total_seconds() / 86400


@pytest.mark.asyncio
class TestMobileRefreshTTL:
    # ─── T-05.1 · mobile login gets the long refresh TTL + ctyp claim ────────
    async def test_t05_1_mobile_login_long_ttl(self, db_session, test_user):
        svc = AuthenticationService(db_session)
        resp = await svc._issue_session(test_user["user"], client_type="mobile")

        row = await _refresh_row(db_session, resp.refresh_token)
        assert (
            settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS_MOBILE - 1
            < _days_until(row.expires_at)
            <= settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS_MOBILE
        )
        # The signed ctyp claim is what carries the TTL across rotations.
        assert verify_token(resp.refresh_token, token_type="refresh")["ctyp"] == "mobile"

    async def test_t05_1_web_login_keeps_short_ttl(self, db_session, test_user):
        svc = AuthenticationService(db_session)
        resp = await svc._issue_session(test_user["user"])  # client_type=None → web

        row = await _refresh_row(db_session, resp.refresh_token)
        assert _days_until(row.expires_at) <= settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
        assert "ctyp" not in verify_token(resp.refresh_token, token_type="refresh")

    async def test_t05_1_mobile_ttl_survives_rotation(self, db_session, test_user):
        svc = AuthenticationService(db_session)
        first = await svc._issue_session(test_user["user"], client_type="mobile")

        rotated = await svc.refresh_access_token(first.refresh_token)

        row = await _refresh_row(db_session, rotated.refresh_token)
        assert _days_until(row.expires_at) > settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
        assert verify_token(rotated.refresh_token, token_type="refresh")["ctyp"] == "mobile"


@pytest.mark.asyncio
class TestPerDeviceRevocation:
    # ─── T-05.7 · revoking device B leaves device A working ──────────────────
    async def test_t05_7_per_device_revocation(self, db_session, test_user):
        svc = AuthenticationService(db_session)
        user = test_user["user"]
        # Two independent logins = two devices = two families.
        device_a = await svc._issue_session(user, client_type="mobile")
        device_b = await svc._issue_session(user, client_type="mobile")
        b_row = await _refresh_row(db_session, device_b.refresh_token)

        revoked = await svc.revoke_device_session(session_id=b_row.id, user_id=user.id)
        assert revoked is True

        # Device B can no longer refresh...
        with pytest.raises(UnauthorizedError):
            await svc.refresh_access_token(device_b.refresh_token)

        # ...but device A is untouched and rotates cleanly.
        rotated_a = await svc.refresh_access_token(device_a.refresh_token)
        assert rotated_a.refresh_token and rotated_a.refresh_token != device_a.refresh_token

    async def test_t05_7_revoke_unknown_session_is_noop(self, db_session, test_user):
        svc = AuthenticationService(db_session)
        assert (
            await svc.revoke_device_session(session_id=uuid4(), user_id=test_user["user"].id)
            is False
        )


async def _store_token_with_tid(db, user, tid) -> str:
    token_data = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "tid": str(tid),
    }
    raw = create_refresh_token(token_data)
    db.add(
        RefreshToken(
            user_id=user.id,
            token=raw,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            family_id=uuid4(),
        )
    )
    await db.commit()
    return raw


def _ctx(tid, slug: str) -> TenantContext:
    return TenantContext(slug=slug, id=tid, tier="starter", display_name=slug)


@pytest.mark.asyncio
class TestRefreshTenantBinding:
    # ─── T-05.8 · a tenant-A refresh rejected against tenant B ───────────────
    async def test_t05_8_tid_mismatch_rejected(self, db_session, test_user):
        svc = AuthenticationService(db_session)
        tid_a, tid_b = uuid4(), uuid4()
        raw = await _store_token_with_tid(db_session, test_user["user"], tid_a)

        marker = set_current_tenant(_ctx(tid_b, "tenant-b"))
        try:
            with pytest.raises(UnauthorizedError) as exc:
                await svc.refresh_access_token(raw)
            assert "mismatch" in str(exc.value).lower()
        finally:
            reset_current_tenant(marker)

    async def test_t05_8_matching_tid_refreshes(self, db_session, test_user):
        svc = AuthenticationService(db_session)
        tid_a = uuid4()
        raw = await _store_token_with_tid(db_session, test_user["user"], tid_a)

        marker = set_current_tenant(_ctx(tid_a, "tenant-a"))
        try:
            resp = await svc.refresh_access_token(raw)
            assert resp.refresh_token and resp.refresh_token != raw
        finally:
            reset_current_tenant(marker)


@pytest.mark.asyncio
class TestAuthFlows:
    # ─── T-05.3 · expired access → refresh → retry, all over HTTP ────────────
    async def test_t05_3_expired_access_then_refresh(
        self, async_client, test_user_with_tokens, expired_token
    ):
        from src.tests.acceptance_helpers import bearer

        # An expired access token is rejected...
        r = await async_client.get("/api/v1/auth/me", headers=bearer(expired_token))
        assert r.status_code == 401

        # ...the client refreshes...
        r = await async_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": test_user_with_tokens["refresh_token"]},
        )
        assert r.status_code == 200
        new_access = r.json()["access_token"]

        # ...and the retry with the fresh access token succeeds.
        r = await async_client.get("/api/v1/auth/me", headers=bearer(new_access))
        assert r.status_code == 200

    # ─── T-05.4 · MFA completion works AND honours mobile TTL ────────────────
    async def test_t05_4_mobile_mfa_completion_long_ttl(self, db_session, test_user):
        import pyotp

        from src.services.mfa_service import MFAService

        user = test_user["user"]
        mfa = MFAService(db_session)
        challenge = await mfa.generate_enrollment(user)
        await mfa.verify_enrollment(
            user, secret=challenge.secret, code=pyotp.TOTP(challenge.secret).now()
        )
        await db_session.commit()

        auth = AuthenticationService(db_session)
        chal = await auth.login(test_user["email"], test_user["password"])
        assert chal.require_mfa is True

        final = await auth.complete_mfa_login(
            challenge_token=chal.mfa_challenge_token,
            code=pyotp.TOTP(challenge.secret).now(),
            client_type="mobile",
        )
        assert final.access_token and final.refresh_token
        row = await _refresh_row(db_session, final.refresh_token)
        assert _days_until(row.expires_at) > settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
        assert verify_token(final.refresh_token, token_type="refresh")["ctyp"] == "mobile"

    # ─── T-05.6 · logout revokes the refresh + bumps the access blocklist ────
    async def test_t05_6_logout_revokes_and_blocklists(
        self, async_client, test_user_with_tokens, monkeypatch
    ):
        import src.core.token_blocklist as bl

        calls = []

        async def _spy(user_id, *, issued_before_epoch):
            calls.append(user_id)

        monkeypatch.setattr(bl, "revoke_user_tokens", _spy)
        rt = test_user_with_tokens["refresh_token"]

        r = await async_client.post("/api/v1/auth/logout", json={"refresh_token": rt})
        assert r.status_code == 200

        # The revoked refresh can no longer mint tokens.
        r = await async_client.post("/api/v1/auth/refresh", json={"refresh_token": rt})
        assert r.status_code == 401
        # And the access-token blocklist marker was bumped for this user.
        assert calls

    # ─── T-05.5 · SSO callback exchanges the code → issues tokens ────────────
    async def test_t05_5_sso_callback_issues_tokens(self, async_client, test_user, monkeypatch):
        from unittest.mock import AsyncMock

        # The PKCE code-for-token exchange (what expo-auth-session drives) is
        # the IdP boundary — mock it to return our user, exactly as a real
        # provider callback would. (tid is asserted by BE-01 in multi-tenant
        # mode; the test env is single-tenant so tid is empty here.)
        monkeypatch.setattr(
            "src.services.auth0_service.Auth0Service.handle_google_callback",
            AsyncMock(return_value=test_user["user"]),
        )
        r = await async_client.get(
            "/api/v1/auth/sso/google/callback", params={"code": "fake-auth-code"}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["access_token"] and body["refresh_token"]
