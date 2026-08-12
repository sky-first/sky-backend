"""Tests for Multi-Factor Authentication (Phase 3 — TOTP).

Covers:

* Enrolment roundtrip (start → verify) persists secret + recovery codes.
* TOTP-based login redemption via AuthenticationService.login →
  complete_mfa_login.
* Recovery codes are single-use.
* Disable MFA wipes secret + recovery codes.
* Sky-team Console gate enforces ``CONSOLE_REQUIRE_MFA``.
* Bad codes raise.
* Challenge token is short-lived and rejects forged payloads.

These tests share the project-wide ``db_session`` + ``test_user``
fixtures in src/tests/conftest.py — same shape as test_auth_service.py.
"""

from __future__ import annotations

import os
import uuid

# ENCRYPTION_KEY needs to be present before any MFAService usage —
# the Fernet helper raises if it's blank. Set a deterministic value
# so encrypt/decrypt roundtrips are reproducible.
os.environ.setdefault("ENCRYPTION_KEY", "test-key-for-mfa-do-not-use-in-prod")

import pyotp  # noqa: E402
import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from src.api.console_auth import require_sky_team  # noqa: E402
from src.config.settings import settings  # noqa: E402
from src.core.exceptions import UnauthorizedError  # noqa: E402
from src.models.user import User  # noqa: E402
from src.services.auth_service import AuthenticationService  # noqa: E402
from src.services.mfa_service import (  # noqa: E402
    MFA_CHALLENGE_TTL_MINUTES,
    MFAService,
    issue_mfa_challenge_token,
    verify_mfa_challenge_token,
)


# ── Enrolment roundtrip ───────────────────────────────────────────────


@pytest.mark.asyncio
class TestMFAEnrollmentRoundtrip:
    async def test_enroll_and_verify_persists_state(
        self, db_session: AsyncSession, test_user: dict
    ):
        user: User = test_user["user"]
        assert user.mfa_enabled is False  # baseline

        mfa = MFAService(db_session)
        challenge = await mfa.generate_enrollment(user)
        assert challenge.secret
        assert challenge.otpauth_url.startswith("otpauth://totp/")
        assert challenge.qrcode_png_b64  # base64 string

        # Use the canonical TOTP generator so the test is independent
        # of wall-clock drift inside the verification window.
        code = pyotp.TOTP(challenge.secret).now()
        result = await mfa.verify_enrollment(user, secret=challenge.secret, code=code)
        await db_session.commit()

        await db_session.refresh(user)
        assert user.mfa_enabled is True
        assert user.mfa_secret_encrypted is not None
        assert user.mfa_recovery_codes_encrypted is not None
        assert user.mfa_enrolled_at is not None
        assert len(result.recovery_codes) == 10

    async def test_verify_enrollment_rejects_bad_code(
        self, db_session: AsyncSession, test_user: dict
    ):
        user: User = test_user["user"]
        mfa = MFAService(db_session)
        challenge = await mfa.generate_enrollment(user)
        with pytest.raises(ValueError):
            await mfa.verify_enrollment(
                user, secret=challenge.secret, code="000000"
            )
        await db_session.refresh(user)
        assert user.mfa_enabled is False


# ── Login flow with TOTP ──────────────────────────────────────────────


@pytest.mark.asyncio
class TestMFALoginFlow:
    async def _enrol(self, db_session: AsyncSession, user: User) -> str:
        mfa = MFAService(db_session)
        challenge = await mfa.generate_enrollment(user)
        code = pyotp.TOTP(challenge.secret).now()
        await mfa.verify_enrollment(user, secret=challenge.secret, code=code)
        await db_session.commit()
        return challenge.secret

    async def test_login_with_mfa_returns_challenge(
        self, db_session: AsyncSession, test_user: dict
    ):
        user = test_user["user"]
        await self._enrol(db_session, user)

        auth = AuthenticationService(db_session)
        response = await auth.login(test_user["email"], test_user["password"])

        assert response.require_mfa is True
        assert response.mfa_challenge_token
        assert response.access_token is None
        assert response.refresh_token is None
        assert response.mfa_expires_in == MFA_CHALLENGE_TTL_MINUTES * 60

    async def test_mfa_exempt_email_signs_in_without_mfa(
        self, db_session: AsyncSession, test_user: dict, monkeypatch
    ):
        """A store-review account on the exempt allowlist skips the MFA gate."""
        user = test_user["user"]
        await self._enrol(db_session, user)  # MFA on — would normally challenge

        from src.services import auth_service as _svc

        monkeypatch.setattr(_svc.settings, "MFA_EXEMPT_EMAILS", test_user["email"])

        auth = AuthenticationService(db_session)
        response = await auth.login(test_user["email"], test_user["password"])

        assert not response.require_mfa
        assert not response.force_enrollment
        assert response.access_token is not None
        assert response.refresh_token is not None

    async def test_mfa_exemption_is_scoped_to_the_allowlist(
        self, db_session: AsyncSession, test_user: dict, monkeypatch
    ):
        """A different email still hits the MFA gate — no accidental bypass."""
        user = test_user["user"]
        await self._enrol(db_session, user)

        from src.services import auth_service as _svc

        monkeypatch.setattr(_svc.settings, "MFA_EXEMPT_EMAILS", "other@example.com")

        auth = AuthenticationService(db_session)
        response = await auth.login(test_user["email"], test_user["password"])
        assert response.require_mfa is True
        assert response.access_token is None

    async def test_complete_mfa_login_issues_tokens(
        self, db_session: AsyncSession, test_user: dict
    ):
        user = test_user["user"]
        secret = await self._enrol(db_session, user)

        auth = AuthenticationService(db_session)
        challenge_response = await auth.login(
            test_user["email"], test_user["password"]
        )
        code = pyotp.TOTP(secret).now()
        final = await auth.complete_mfa_login(
            challenge_token=challenge_response.mfa_challenge_token,
            code=code,
        )

        assert final.access_token is not None
        assert final.refresh_token is not None
        assert final.user is not None
        assert final.user.email == test_user["email"]

    async def test_complete_mfa_rejects_wrong_code(
        self, db_session: AsyncSession, test_user: dict
    ):
        user = test_user["user"]
        await self._enrol(db_session, user)

        auth = AuthenticationService(db_session)
        challenge_response = await auth.login(
            test_user["email"], test_user["password"]
        )
        with pytest.raises(UnauthorizedError):
            await auth.complete_mfa_login(
                challenge_token=challenge_response.mfa_challenge_token,
                code="000000",
            )

    async def test_complete_mfa_rejects_forged_challenge(
        self, db_session: AsyncSession, test_user: dict
    ):
        user = test_user["user"]
        await self._enrol(db_session, user)

        auth = AuthenticationService(db_session)
        with pytest.raises(UnauthorizedError):
            await auth.complete_mfa_login(
                challenge_token="not.a.valid.jwt",
                code="123456",
            )


# ── Recovery codes ────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestRecoveryCodes:
    async def test_consume_recovery_code_is_single_use(
        self, db_session: AsyncSession, test_user: dict
    ):
        user = test_user["user"]
        mfa = MFAService(db_session)
        challenge = await mfa.generate_enrollment(user)
        code = pyotp.TOTP(challenge.secret).now()
        result = await mfa.verify_enrollment(
            user, secret=challenge.secret, code=code
        )
        await db_session.commit()

        recovery_code = result.recovery_codes[0]
        assert await mfa.consume_recovery_code(user, recovery_code) is True
        # Second attempt must fail — single use.
        assert await mfa.consume_recovery_code(user, recovery_code) is False

    async def test_rotate_recovery_codes_invalidates_old_batch(
        self, db_session: AsyncSession, test_user: dict
    ):
        user = test_user["user"]
        mfa = MFAService(db_session)
        challenge = await mfa.generate_enrollment(user)
        code = pyotp.TOTP(challenge.secret).now()
        first_result = await mfa.verify_enrollment(
            user, secret=challenge.secret, code=code
        )
        old_code = first_result.recovery_codes[0]

        new_codes = await mfa.rotate_recovery_codes(user)
        await db_session.commit()
        assert len(new_codes) == 10
        # Old code no longer valid.
        assert await mfa.consume_recovery_code(user, old_code) is False
        # A new code works.
        assert await mfa.consume_recovery_code(user, new_codes[0]) is True


# ── Disable ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDisableMFA:
    async def test_disable_wipes_credentials(
        self, db_session: AsyncSession, test_user: dict
    ):
        user = test_user["user"]
        mfa = MFAService(db_session)
        challenge = await mfa.generate_enrollment(user)
        code = pyotp.TOTP(challenge.secret).now()
        await mfa.verify_enrollment(user, secret=challenge.secret, code=code)
        await db_session.commit()
        assert user.mfa_enabled is True

        await mfa.disable_mfa(user)
        await db_session.commit()
        await db_session.refresh(user)
        assert user.mfa_enabled is False
        assert user.mfa_secret_encrypted is None
        assert user.mfa_recovery_codes_encrypted is None


# ── Console enforcement gate ──────────────────────────────────────────


@pytest.mark.asyncio
class TestSkyTeamMFAEnforcement:
    async def test_console_blocks_operator_without_mfa_when_flag_on(
        self,
        db_session: AsyncSession,
        monkeypatch,
    ):
        """When CONSOLE_REQUIRE_MFA=True a Sky-team operator without
        MFA gets a 403 with the ``mfa_required`` body so the FE can
        redirect them to /mfa/enroll/start.
        """
        # Force the dev-bypass off so the test exercises the real
        # path (the bypass would synthesise a user that passes anyway).
        monkeypatch.delenv("CONSOLE_DEV_BYPASS", raising=False)
        monkeypatch.delenv("CONSOLE_ALLOWED_EMAILS", raising=False)
        monkeypatch.setattr(settings, "CONSOLE_REQUIRE_MFA", True)

        operator = User(
            id=uuid.uuid4(),
            email="operator@skyfirstlabs.com",
            password_hash="",
            name="Op",
            role="admin",
            email_verified=True,
            has_completed_onboarding=True,
            is_sky_operator=True,
            mfa_enabled=False,
        )

        async def fake_current_user(*args, **kwargs):
            return operator

        monkeypatch.setattr("src.api.console_auth.get_current_user", fake_current_user)

        from starlette.requests import Request

        # Host header satisfies the Console host-isolation gate (PR #487);
        # without it the dependency rejects 404 before touching MFA.
        scope = {
            "type": "http",
            "headers": [(b"host", b"console-stg.skyfirstlabs.com")],
            "method": "GET",
            "path": "/",
        }
        request = Request(scope=scope)

        with pytest.raises(HTTPException) as exc:
            await require_sky_team(request=request, db=db_session)
        assert exc.value.status_code == 403
        assert exc.value.detail.get("error") == "mfa_required"

    async def test_console_allows_operator_with_mfa_when_flag_on(
        self,
        db_session: AsyncSession,
        monkeypatch,
    ):
        monkeypatch.delenv("CONSOLE_DEV_BYPASS", raising=False)
        monkeypatch.delenv("CONSOLE_ALLOWED_EMAILS", raising=False)
        monkeypatch.setattr(settings, "CONSOLE_REQUIRE_MFA", True)

        operator = User(
            id=uuid.uuid4(),
            email="operator@skyfirstlabs.com",
            password_hash="",
            name="Op",
            role="admin",
            email_verified=True,
            has_completed_onboarding=True,
            is_sky_operator=True,
            mfa_enabled=True,
        )

        async def fake_current_user(*args, **kwargs):
            return operator

        monkeypatch.setattr("src.api.console_auth.get_current_user", fake_current_user)

        from starlette.requests import Request

        # Host header satisfies the Console host-isolation gate (PR #487);
        # without it the dependency rejects 404 before touching MFA.
        scope = {
            "type": "http",
            "headers": [(b"host", b"console-stg.skyfirstlabs.com")],
            "method": "GET",
            "path": "/",
        }
        request = Request(scope=scope)

        user = await require_sky_team(request=request, db=db_session)
        assert user.email == "operator@skyfirstlabs.com"

    async def test_console_does_not_enforce_when_flag_off(
        self,
        db_session: AsyncSession,
        monkeypatch,
    ):
        """Default posture (flag off) — operator without MFA is allowed."""
        monkeypatch.delenv("CONSOLE_DEV_BYPASS", raising=False)
        monkeypatch.delenv("CONSOLE_ALLOWED_EMAILS", raising=False)
        monkeypatch.setattr(settings, "CONSOLE_REQUIRE_MFA", False)

        operator = User(
            id=uuid.uuid4(),
            email="operator@skyfirstlabs.com",
            password_hash="",
            name="Op",
            role="admin",
            email_verified=True,
            has_completed_onboarding=True,
            is_sky_operator=True,
            mfa_enabled=False,
        )

        async def fake_current_user(*args, **kwargs):
            return operator

        monkeypatch.setattr("src.api.console_auth.get_current_user", fake_current_user)

        from starlette.requests import Request

        # Host header satisfies the Console host-isolation gate (PR #487);
        # without it the dependency rejects 404 before touching MFA.
        scope = {
            "type": "http",
            "headers": [(b"host", b"console-stg.skyfirstlabs.com")],
            "method": "GET",
            "path": "/",
        }
        request = Request(scope=scope)

        user = await require_sky_team(request=request, db=db_session)
        assert user.email == "operator@skyfirstlabs.com"


# ── Challenge token helpers ──────────────────────────────────────────


def test_challenge_token_roundtrip():
    user = User(
        id=uuid.uuid4(),
        email="x@example.com",
        password_hash="",
        name="x",
        role="user",
        email_verified=True,
        has_completed_onboarding=True,
    )
    token = issue_mfa_challenge_token(user)
    sub = verify_mfa_challenge_token(token)
    assert sub == str(user.id)


def test_challenge_token_rejects_garbage():
    with pytest.raises(ValueError):
        verify_mfa_challenge_token("definitely.not.a.jwt")


# ── Forced first-login enrolment (Lucas decision 2026-05-31) ────────


def test_enrollment_token_carries_secret():
    """The enrolment token must round-trip both the user id and the
    candidate TOTP secret so the BE can persist it at /mfa-finalize
    without ever storing it server-side beforehand."""
    from src.services.mfa_service import (
        issue_mfa_enrollment_token,
        verify_mfa_enrollment_token,
    )

    user = User(
        id=uuid.uuid4(),
        email="x@example.com",
        password_hash="hashed",
        name="x",
        role="user",
        email_verified=True,
        has_completed_onboarding=True,
    )
    secret = pyotp.random_base32()
    token = issue_mfa_enrollment_token(user, secret)
    sub, recovered = verify_mfa_enrollment_token(token)
    assert sub == str(user.id)
    assert recovered == secret


def test_enrollment_token_rejects_challenge_token_type():
    """Cross-type replay defence: a login-challenge token must NOT
    pass verify_enrollment_token (different ``type`` claim)."""
    from src.services.mfa_service import (
        issue_mfa_challenge_token,
        verify_mfa_enrollment_token,
    )

    user = User(
        id=uuid.uuid4(),
        email="x@example.com",
        password_hash="hashed",
        name="x",
        role="user",
        email_verified=True,
        has_completed_onboarding=True,
    )
    challenge = issue_mfa_challenge_token(user)
    with pytest.raises(ValueError):
        verify_mfa_enrollment_token(challenge)


@pytest.mark.asyncio
async def test_persist_enrollment_writes_secret_and_codes(db_session: AsyncSession):
    """persist_enrollment finalises a forced first-login flow:
    the secret arrives as a function argument (recovered from the
    JWT-bound token, not from the DB) and is what gets persisted."""
    from src.services.mfa_service import MFAService

    user = User(
        id=uuid.uuid4(),
        email="newuser@gbt.pt",
        password_hash="hashed",
        name="New",
        role="user",
        email_verified=True,
        has_completed_onboarding=True,
        mfa_enabled=False,
    )
    db_session.add(user)
    await db_session.flush()

    mfa = MFAService(db_session)
    secret = pyotp.random_base32()
    valid_code = pyotp.TOTP(secret).now()
    result = await mfa.persist_enrollment(user, secret=secret, code=valid_code)

    assert user.mfa_enabled is True
    assert user.mfa_secret_encrypted is not None
    assert user.mfa_recovery_codes_encrypted is not None
    assert user.mfa_enrolled_at is not None
    assert len(result.recovery_codes) == 10


@pytest.mark.asyncio
async def test_persist_enrollment_refuses_when_already_enabled(db_session: AsyncSession):
    """Refuses 'mfa_already_enabled' when the user is already enrolled
    — protects against an attacker replaying a stale enrolment token."""
    from src.services.mfa_service import MFAService

    user = User(
        id=uuid.uuid4(),
        email="legit@gbt.pt",
        password_hash="hashed",
        name="Legit",
        role="user",
        email_verified=True,
        has_completed_onboarding=True,
        mfa_enabled=True,
    )
    db_session.add(user)
    await db_session.flush()

    mfa = MFAService(db_session)
    secret = pyotp.random_base32()
    valid_code = pyotp.TOTP(secret).now()
    with pytest.raises(ValueError) as exc:
        await mfa.persist_enrollment(user, secret=secret, code=valid_code)
    assert str(exc.value) == "mfa_already_enabled"


@pytest.mark.asyncio
async def test_persist_enrollment_rejects_bad_code(db_session: AsyncSession):
    from src.services.mfa_service import MFAService

    user = User(
        id=uuid.uuid4(),
        email="bad-code@gbt.pt",
        password_hash="hashed",
        name="x",
        role="user",
        email_verified=True,
        has_completed_onboarding=True,
        mfa_enabled=False,
    )
    db_session.add(user)
    await db_session.flush()

    mfa = MFAService(db_session)
    secret = pyotp.random_base32()
    with pytest.raises(ValueError):
        await mfa.persist_enrollment(user, secret=secret, code="000000")
    # MFA stayed off + nothing persisted.
    assert user.mfa_enabled is False
    assert user.mfa_secret_encrypted is None
