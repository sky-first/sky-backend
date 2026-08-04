"""BE-05 · Refresh-token rotation with reuse detection — T-05.1…T-05.6.

Rotation already existed; what this suite locks in is the *family* behaviour:
replaying a token that was already rotated (theft) revokes the whole login
lineage, while unrelated logins stay untouched.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import UnauthorizedError
from src.core.security import create_refresh_token
from src.models.user import RefreshToken
from src.services.auth_service import AuthenticationService


async def _store_login_token(
    db: AsyncSession,
    user,
    *,
    family_id=None,
    expires_delta: timedelta = timedelta(days=7),
):
    """Persist a refresh token as if a fresh login had just minted it."""
    token_data = {"sub": str(user.id), "email": user.email, "role": user.role}
    raw = create_refresh_token(token_data)
    row = RefreshToken(
        user_id=user.id,
        token=raw,
        expires_at=datetime.now(timezone.utc) + expires_delta,
        family_id=family_id or uuid4(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return raw, row


async def _row(db: AsyncSession, token: str) -> RefreshToken:
    result = await db.execute(select(RefreshToken).where(RefreshToken.token == token))
    return result.scalar_one_or_none()


@pytest.mark.asyncio
class TestRefreshReuse:
    # ─── T-05.1 · happy rotation stays in the same family ────────────────────
    async def test_t05_1_rotation_keeps_family(self, db_session, test_user):
        svc = AuthenticationService(db_session)
        raw, row = await _store_login_token(db_session, test_user["user"])
        family = row.family_id

        resp = await svc.refresh_access_token(raw)

        assert resp.access_token and resp.refresh_token != raw
        old = await _row(db_session, raw)
        new = await _row(db_session, resp.refresh_token)
        assert old.revoked_at is not None  # parent rotated out
        assert new.revoked_at is None
        assert new.family_id == family  # child inherits the lineage

    # ─── T-05.2 · replaying a rotated token nukes the whole family ───────────
    async def test_t05_2_reuse_revokes_family(self, db_session, test_user):
        svc = AuthenticationService(db_session)
        raw_a, _ = await _store_login_token(db_session, test_user["user"])

        resp = await svc.refresh_access_token(raw_a)  # A → B (A now revoked)
        raw_b = resp.refresh_token

        # 🚨 Replay A (the already-rotated token).
        with pytest.raises(UnauthorizedError) as exc:
            await svc.refresh_access_token(raw_a)
        assert "reuse" in str(exc.value).lower()

        # The still-live child B must now be revoked too — the family is dead.
        assert (await _row(db_session, raw_b)).revoked_at is not None

    # ─── T-05.3 · after reuse, even the newest token can't refresh ───────────
    async def test_t05_3_family_dead_newest_token_fails(self, db_session, test_user):
        svc = AuthenticationService(db_session)
        raw_a, _ = await _store_login_token(db_session, test_user["user"])
        raw_b = (await svc.refresh_access_token(raw_a)).refresh_token

        with pytest.raises(UnauthorizedError):
            await svc.refresh_access_token(raw_a)  # trip the reuse detector

        # B was revoked by the nuke → replaying it is itself reuse, not a 401.
        with pytest.raises(UnauthorizedError) as exc:
            await svc.refresh_access_token(raw_b)
        assert "reuse" in str(exc.value).lower()

    # ─── T-05.4 · an unrelated login family is untouched ─────────────────────
    async def test_t05_4_other_family_survives(self, db_session, test_user):
        svc = AuthenticationService(db_session)
        user = test_user["user"]
        raw_a, _ = await _store_login_token(db_session, user)  # family 1
        raw_c, row_c = await _store_login_token(db_session, user)  # family 2
        assert row_c.family_id is not None

        await svc.refresh_access_token(raw_a)  # rotate family 1
        with pytest.raises(UnauthorizedError):
            await svc.refresh_access_token(raw_a)  # nuke family 1

        # Family 2 never touched → still rotates cleanly.
        resp = await svc.refresh_access_token(raw_c)
        assert resp.refresh_token and resp.refresh_token != raw_c

    # ─── T-05.5 · a token we never issued → plain 401, no nuke ───────────────
    async def test_t05_5_unknown_token_is_invalid(self, db_session, test_user):
        svc = AuthenticationService(db_session)
        user = test_user["user"]
        live_raw, _ = await _store_login_token(db_session, user)

        # Valid signature, but never persisted.
        ghost = create_refresh_token({"sub": str(user.id), "email": user.email, "role": user.role})
        with pytest.raises(UnauthorizedError) as exc:
            await svc.refresh_access_token(ghost)
        assert "invalid" in str(exc.value).lower()

        # Nothing was nuked — the genuine live token still works.
        assert (await _row(db_session, live_raw)).revoked_at is None

    # ─── T-05.6 · an expired (but valid-signature) token → 401 ───────────────
    async def test_t05_6_expired_token(self, db_session, test_user):
        svc = AuthenticationService(db_session)
        raw, _ = await _store_login_token(
            db_session, test_user["user"], expires_delta=timedelta(days=-1)
        )
        with pytest.raises(UnauthorizedError) as exc:
            await svc.refresh_access_token(raw)
        assert "expired" in str(exc.value).lower()

    # ─── T-05.7 · the REAL issuance path opens a family ──────────────────────
    async def test_t05_7_real_login_opens_a_family(self, db_session, test_user):
        # The whole scheme rests on a real login opening a family. Exercise the
        # shared issuance path (login / MFA / SSO / select-workspace all funnel
        # through _issue_session) instead of the injected helper, so a broken
        # stamp is actually caught here.
        svc = AuthenticationService(db_session)
        resp = await svc._issue_session(test_user["user"])
        row = await _row(db_session, resp.refresh_token)
        assert row is not None
        assert row.family_id is not None  # login lineage was stamped

    # ─── T-05.8 · reuse also bumps the access-token blocklist (Option A) ─────
    async def test_t05_8_reuse_bumps_access_blocklist(self, db_session, test_user, monkeypatch):
        # Redis is absent under test, so the real revoke_user_tokens is a no-op.
        # Spy on it to prove Option A actually fires with the right arguments.
        import src.core.token_blocklist as bl

        calls = []

        async def _spy(user_id, *, issued_before_epoch):
            calls.append((user_id, issued_before_epoch))

        monkeypatch.setattr(bl, "revoke_user_tokens", _spy)

        svc = AuthenticationService(db_session)
        raw_a, _ = await _store_login_token(db_session, test_user["user"])
        await svc.refresh_access_token(raw_a)  # rotate A → B
        with pytest.raises(UnauthorizedError):
            await svc.refresh_access_token(raw_a)  # reuse → must bump blocklist

        assert len(calls) == 1
        assert calls[0][0] == str(test_user["user"].id)
        assert isinstance(calls[0][1], int)  # epoch second
