"""Multi-Factor Authentication service (TOTP — Phase 3).

Implements RFC 6238 time-based one-time passwords on top of the
existing local-password + SSO login flows. Enrolment is opt-in for
tenant users; Sky-team operators (Console) get a separate
enforcement gate driven by ``CONSOLE_REQUIRE_MFA`` (off until the
rollout date — see open questions in the PR description).

Threat model notes:

* TOTP secret + recovery codes are Fernet-encrypted with
  ``ENCRYPTION_KEY`` before they touch the DB. A SELECT * dump of
  ``users`` does not yield working seeds.
* Recovery codes are bcrypt-hashed *inside* the encrypted JSON
  payload — single-use, shown to the user exactly once at
  enrolment time. The hashed-and-encrypted shape means a recovery
  code is useless to anyone who only has DB access (they would
  also need ``ENCRYPTION_KEY``) and is useless to anyone who only
  has ``ENCRYPTION_KEY`` (they would also need to brute-force
  bcrypt).
* TOTP verification accepts a ±1 step window (30s on each side)
  to handle clock drift, matching every major authenticator app.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import bcrypt
import pyotp
import qrcode
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.models.user import User

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────
# Number of recovery codes minted at enrolment time. Ten matches the
# convention used by Google, GitHub, Stripe and Notion — enough for a
# realistic device loss + travel scenario, few enough that the user
# can reasonably write them down.
RECOVERY_CODE_COUNT = 10
# Each recovery code is 10 hex chars (~40 bits of entropy) split into
# two five-char blocks for legibility ("a1b2c-d3e4f"). The split is
# cosmetic; verification normalises by stripping non-alnum.
_RECOVERY_CODE_RAW_BYTES = 5  # → 10 hex chars
# Issuer label shown in the authenticator app. Includes the tenant
# slug when available so users with accounts on multiple workspaces
# can tell them apart. Falls back to "SkyFirst" on the bare landing.
DEFAULT_ISSUER = "SkyFirst"
# RFC 6238 acceptance window. ``valid_window=1`` means the last and
# next step are also accepted in addition to the current one.
TOTP_VALID_WINDOW = 1


# ── Fernet helper ─────────────────────────────────────────────────────
# Mirrors the logic in src/utils/encryption.py but operates on raw
# bytes (the User columns are BYTEA, not JSONB). Keeping it local here
# avoids polluting the public encryption helper with an alternate
# binary-only API surface.

def _fernet() -> Fernet:
    key = settings.ENCRYPTION_KEY or os.getenv("ENCRYPTION_KEY") or ""
    if not key:
        raise RuntimeError(
            "MFA requires ENCRYPTION_KEY to be configured — secret + "
            "recovery codes are stored encrypted at rest."
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        # The dev default ("your-32-byte-encryption-key-change-in-...")
        # is not a valid Fernet key; derive one via SHA-256 so the
        # local stack still boots without a manual key swap.
        derived = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
        return Fernet(derived)


def _encrypt(plaintext: bytes) -> bytes:
    return _fernet().encrypt(plaintext)


def _decrypt(ciphertext: bytes) -> bytes:
    return _fernet().decrypt(ciphertext)


# ── Result containers ─────────────────────────────────────────────────


@dataclass
class EnrollmentChallenge:
    """Returned by ``generate_enrollment`` — held in memory until the
    user confirms with their first code. The secret is NOT persisted
    until ``verify_enrollment`` succeeds, so an abandoned enrolment
    leaves no DB row to clean up.
    """

    secret: str
    otpauth_url: str
    qrcode_png_b64: str


@dataclass
class EnrollmentResult:
    """Returned by ``verify_enrollment`` once the user proves they
    have the secret in their authenticator app. The plaintext
    recovery codes are present exactly here — the FE shows them to
    the user once (copy + download .txt) and the BE never returns
    them again.
    """

    recovery_codes: List[str]
    enrolled_at: datetime


# ── Public API ────────────────────────────────────────────────────────


class MFAService:
    """All MFA-related operations on a user.

    Each method takes an already-loaded ``User`` row from the caller's
    AsyncSession so we don't re-fetch by id in the hot path. Mutations
    flush to the session but do NOT commit — the caller controls the
    transaction boundary (mirrors the convention used by
    AuthenticationService).
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Enrolment ────────────────────────────────────────────────────

    async def generate_enrollment(
        self,
        user: User,
        *,
        issuer: Optional[str] = None,
    ) -> EnrollmentChallenge:
        """Mint a new TOTP secret + otpauth URL + QR code.

        The secret is NOT persisted yet — we return it to the FE so
        the user can scan the QR. They must then call
        ``verify_enrollment`` with a valid 6-digit code; only then do
        we encrypt and store the secret. This prevents a half-enrolled
        state where ``mfa_enabled`` is true but the user can't actually
        log in because they closed the modal before scanning.

        The enrolment secret is base32 (RFC 4648) per the TOTP spec.
        We hand it to the FE plain — it's already in the page that
        the authenticated user is looking at and there is no useful
        attacker model where the FE has the secret but not the user's
        password.
        """
        secret = pyotp.random_base32()
        label = user.email or str(user.id)
        # Use a stable issuer string so the authenticator app groups
        # all SkyFirst-hosted workspaces under one tile.
        issuer_name = issuer or DEFAULT_ISSUER
        otpauth_url = pyotp.TOTP(secret).provisioning_uri(
            name=label, issuer_name=issuer_name
        )

        qrcode_png_b64 = _render_qrcode_png_b64(otpauth_url)

        return EnrollmentChallenge(
            secret=secret,
            otpauth_url=otpauth_url,
            qrcode_png_b64=qrcode_png_b64,
        )

    async def verify_enrollment(
        self,
        user: User,
        *,
        secret: str,
        code: str,
    ) -> EnrollmentResult:
        """Confirm enrolment by checking the user's first TOTP code.

        On success persists:
          * ``mfa_enabled = true``
          * ``mfa_secret_encrypted`` — Fernet(``secret``)
          * ``mfa_recovery_codes_encrypted`` — Fernet(JSON of bcrypt-hashed codes)
          * ``mfa_enrolled_at`` — now

        ``ValueError`` on a bad code; the caller maps that to a 400.
        """
        if not _verify_totp(secret, code):
            raise ValueError("invalid_code")

        plaintext_codes = _mint_recovery_codes(RECOVERY_CODE_COUNT)
        encrypted_codes = _encrypt(_encode_recovery_codes(plaintext_codes))
        encrypted_secret = _encrypt(secret.encode("utf-8"))
        now = datetime.now(timezone.utc)

        user.mfa_secret_encrypted = encrypted_secret
        user.mfa_recovery_codes_encrypted = encrypted_codes
        user.mfa_enabled = True
        user.mfa_enrolled_at = now
        await self.db.flush()

        return EnrollmentResult(recovery_codes=plaintext_codes, enrolled_at=now)

    # ── Login-time verification ──────────────────────────────────────

    async def verify_login_code(self, user: User, code: str) -> bool:
        """Verify a 6-digit TOTP code presented at login.

        Returns False (instead of raising) so the calling handler can
        decide whether to emit a 401 vs reuse the challenge token for
        another attempt. Updates ``mfa_last_used_at`` on success.
        """
        if not user.mfa_enabled or not user.mfa_secret_encrypted:
            return False
        try:
            secret = _decrypt(user.mfa_secret_encrypted).decode("utf-8")
        except InvalidToken:
            logger.error("mfa.verify_login_code.decrypt_failed user=%s", user.id)
            return False

        if not _verify_totp(secret, code):
            return False

        user.mfa_last_used_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True

    async def consume_recovery_code(self, user: User, code: str) -> bool:
        """Consume one recovery code (single-use).

        Returns False if no slot matches. On match, marks that slot as
        used inside the encrypted JSON blob and writes it back.
        ``mfa_last_used_at`` is bumped so the Console can flag a 2FA
        setup that has only ever logged in via recovery (= the user
        lost their device but didn't re-enrol).
        """
        if not user.mfa_enabled or not user.mfa_recovery_codes_encrypted:
            return False
        try:
            payload = json.loads(_decrypt(user.mfa_recovery_codes_encrypted))
        except (InvalidToken, ValueError):
            logger.error("mfa.consume_recovery.decrypt_failed user=%s", user.id)
            return False

        normalised = _normalise_code(code)
        if not normalised:
            return False

        matched_index: Optional[int] = None
        for i, slot in enumerate(payload):
            if slot.get("used"):
                continue
            stored_hash = slot.get("hash", "")
            if not stored_hash:
                continue
            try:
                if bcrypt.checkpw(normalised.encode("utf-8"), stored_hash.encode("utf-8")):
                    matched_index = i
                    break
            except Exception:  # noqa: BLE001
                continue

        if matched_index is None:
            return False

        payload[matched_index]["used"] = True
        payload[matched_index]["used_at"] = datetime.now(timezone.utc).isoformat()
        user.mfa_recovery_codes_encrypted = _encrypt(
            json.dumps(payload).encode("utf-8")
        )
        user.mfa_last_used_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True

    async def rotate_recovery_codes(self, user: User) -> List[str]:
        """Mint a fresh batch of recovery codes, invalidating the old.

        Used by the user from Settings → Security after they consume
        codes on lost-device events, or as routine hygiene. Returns
        plaintext codes once — same UX contract as enrolment.
        """
        if not user.mfa_enabled:
            raise ValueError("mfa_not_enabled")
        plaintext_codes = _mint_recovery_codes(RECOVERY_CODE_COUNT)
        user.mfa_recovery_codes_encrypted = _encrypt(
            _encode_recovery_codes(plaintext_codes)
        )
        await self.db.flush()
        return plaintext_codes

    # ── Forced first-login enrolment ────────────────────────────────

    async def persist_enrollment(
        self, user: User, *, secret: str, code: str
    ) -> EnrollmentResult:
        """Persist an enrolment recovered from a JWT-bound secret.

        Used by the /auth/login/mfa-finalize flow: the BE issued an
        enrolment token at /auth/login (when it found mfa_enabled=false
        on a password-authenticated account), the FE collected the
        user's first 6-digit TOTP code, and now we verify + persist.

        Refuses if the user already has MFA enabled — protects against
        an attacker replaying an enrolment token after the legitimate
        owner has already finished onboarding.
        """
        if getattr(user, "mfa_enabled", False):
            raise ValueError("mfa_already_enabled")
        if not _verify_totp(secret, code):
            raise ValueError("invalid_code")

        plaintext_codes = _mint_recovery_codes(RECOVERY_CODE_COUNT)
        encrypted_codes = _encrypt(_encode_recovery_codes(plaintext_codes))
        encrypted_secret = _encrypt(secret.encode("utf-8"))
        now = datetime.now(timezone.utc)

        user.mfa_secret_encrypted = encrypted_secret
        user.mfa_recovery_codes_encrypted = encrypted_codes
        user.mfa_enabled = True
        user.mfa_enrolled_at = now
        await self.db.flush()

        return EnrollmentResult(recovery_codes=plaintext_codes, enrolled_at=now)

    # ── Disable ──────────────────────────────────────────────────────

    async def disable_mfa(self, user: User) -> None:
        """Turn MFA off and wipe the stored secret + recovery codes.

        Owner-only flow at the API layer (we don't check role here so
        admin-impersonation can call it for a locked-out customer).
        Leaves ``mfa_enrolled_at`` / ``mfa_last_used_at`` intact for
        audit — they're metadata, not credentials.

        Note (2026-05-31): the public /mfa DELETE endpoint was removed;
        regular users cannot turn MFA off themselves once enrolled. This
        method survives for admin-impersonation use cases (locked-out
        customer support flows).
        """
        user.mfa_enabled = False
        user.mfa_secret_encrypted = None
        user.mfa_recovery_codes_encrypted = None
        await self.db.flush()


# ── Private helpers ───────────────────────────────────────────────────


def _verify_totp(secret: str, code: str) -> bool:
    """Return True iff ``code`` is a valid TOTP for ``secret``.

    Accepts a ±1 step window for clock drift; uses constant-time
    compare via pyotp.verify.
    """
    if not code or not code.isdigit() or len(code) != 6:
        return False
    try:
        return pyotp.TOTP(secret).verify(code, valid_window=TOTP_VALID_WINDOW)
    except Exception:  # noqa: BLE001
        return False


def _render_qrcode_png_b64(payload: str) -> str:
    """Render ``payload`` as a base64-encoded PNG (UTF-8 string).

    Box size + border picked to render well at ~200px wide on a
    desktop modal — Google Authenticator scans this size reliably
    without needing to focus.
    """
    img = qrcode.make(payload, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _normalise_code(code: str) -> str:
    """Strip whitespace/dashes and lowercase — recovery codes are
    displayed as ``a1b2c-d3e4f`` but the user may paste either form.
    """
    if not code:
        return ""
    return "".join(c for c in code if c.isalnum()).lower()


def _mint_recovery_codes(count: int) -> List[str]:
    codes = []
    for _ in range(count):
        raw = secrets.token_hex(_RECOVERY_CODE_RAW_BYTES)  # 10 hex chars
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def _encode_recovery_codes(plaintext_codes: List[str]) -> bytes:
    """Bcrypt-hash each recovery code and pack as JSON bytes.

    Layout::

        [
          {"hash": "<bcrypt>", "used": false, "used_at": null},
          ...
        ]

    Stored as the plaintext payload that ``_encrypt`` then Fernet-wraps
    before it lands in ``mfa_recovery_codes_encrypted``.
    """
    payload = []
    for code in plaintext_codes:
        normalised = _normalise_code(code)
        hashed = bcrypt.hashpw(
            normalised.encode("utf-8"), bcrypt.gensalt(rounds=10)
        ).decode("utf-8")
        payload.append({"hash": hashed, "used": False, "used_at": None})
    return json.dumps(payload).encode("utf-8")


# ── MFA challenge token helpers ───────────────────────────────────────
# Short-lived (5min) JWT issued by the login endpoint once email +
# password are validated but before MFA is satisfied. The FE redeems
# it at POST /auth/login/mfa with the user's 6-digit code; on success
# the BE issues the real access + refresh pair.

MFA_CHALLENGE_TYPE = "mfa_challenge"
MFA_CHALLENGE_TTL_MINUTES = 5


def issue_mfa_challenge_token(user: User) -> str:
    """Issue a short-lived JWT that authorises a /login/mfa attempt.

    Locally signed with the same JWT_SECRET_KEY as access tokens to
    avoid introducing a new key; the ``type`` claim is distinct so
    middleware never confuses it with an access token.
    """
    from datetime import timedelta

    from jose import jwt

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "type": MFA_CHALLENGE_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=MFA_CHALLENGE_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_mfa_challenge_token(token: str) -> str:
    """Verify a challenge token and return the user_id (``sub``).

    Raises ``ValueError`` with a stable code on any failure — the
    caller maps it to a 401.
    """
    from jose import JWTError, jwt

    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError as exc:
        raise ValueError("invalid_challenge_token") from exc
    if payload.get("type") != MFA_CHALLENGE_TYPE:
        raise ValueError("invalid_challenge_token_type")
    sub = payload.get("sub")
    if not sub:
        raise ValueError("invalid_challenge_token_payload")
    return str(sub)


# ── MFA enrollment token helpers ───────────────────────────────────────
# Different beast from the login-challenge token: this one is issued
# when a password-authenticated user logs in for the FIRST time on an
# account that hasn't enrolled MFA yet. The payload carries the freshly
# minted TOTP secret so the user can scan the QR + come back with the
# 6-digit code; on /auth/login/mfa-finalize the BE recovers the secret
# from this token (NOT from the DB — it isn't persisted yet) and only
# then writes it to the user row.
#
# Why bake the secret into the token instead of persisting it server-
# side and looking it up by id? Two reasons:
#   1. No extra DB write on an enrolment the user might abandon.
#   2. JWT signature guarantees the secret the BE persists at
#      finalize-time is the same one the user actually scanned —
#      no race / replay window between two parallel enrolment attempts.
# The TTL is long enough for an unhurried user (10min) but short
# enough that a stolen token quickly expires.

MFA_ENROLLMENT_TYPE = "mfa_enrollment"
MFA_ENROLLMENT_TTL_MINUTES = 10


def issue_mfa_enrollment_token(user: User, secret: str) -> str:
    """Issue a short-lived JWT that authorises /login/mfa-finalize.

    Embeds the candidate TOTP secret so the BE doesn't have to persist
    enrolment state for an attempt the user might abandon. The token
    is single-use in practice: once the secret is persisted on the
    user row, replay can't enrol the user twice (the service refuses
    when ``mfa_enabled`` is already true).
    """
    from datetime import timedelta

    from jose import jwt

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "secret": secret,
        "type": MFA_ENROLLMENT_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=MFA_ENROLLMENT_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_mfa_enrollment_token(token: str) -> tuple[str, str]:
    """Verify an enrolment token. Returns ``(user_id, secret)``.

    Raises ``ValueError`` with a stable code on any failure — the
    caller maps it to a 401.
    """
    from jose import JWTError, jwt

    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError as exc:
        raise ValueError("invalid_enrollment_token") from exc
    if payload.get("type") != MFA_ENROLLMENT_TYPE:
        raise ValueError("invalid_enrollment_token_type")
    sub = payload.get("sub")
    secret = payload.get("secret")
    if not sub or not secret:
        raise ValueError("invalid_enrollment_token_payload")
    return str(sub), str(secret)


__all__ = [
    "EnrollmentChallenge",
    "EnrollmentResult",
    "MFAService",
    "MFA_CHALLENGE_TTL_MINUTES",
    "MFA_ENROLLMENT_TTL_MINUTES",
    "RECOVERY_CODE_COUNT",
    "issue_mfa_challenge_token",
    "verify_mfa_challenge_token",
    "issue_mfa_enrollment_token",
    "verify_mfa_enrollment_token",
]
