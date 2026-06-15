"""Password-reset service (forgot-password / reset-password).

Mirrors :mod:`src.services.invite_service` conventions:

* ``secrets.token_urlsafe(32)`` for the token (same entropy as invites).
* Token + expiry stored on the ``User`` row; cleared on consumption.
* Email sent best-effort via :class:`EmailService` — a delivery failure
  (e.g. SES sandbox rejecting an unverified recipient) is swallowed and
  never surfaces to the caller, so ``forgot-password`` always returns the
  same generic 200 regardless of whether the user exists or the email
  went out. That is what prevents account-existence enumeration.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.core.exceptions import BadRequestError
from src.core.security import get_password_hash
from src.models.user import User
from src.services.email_service import EmailService

logger = logging.getLogger(__name__)

# Reset tokens are short-lived — an hour is plenty for a user to click the
# link in the email they just requested, and short enough that a leaked
# token has a tiny window of validity.
RESET_TOKEN_TTL = timedelta(hours=1)


class PasswordResetService:
    """Service for self-service password recovery."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def request_reset(
        self,
        email: str,
        base_url: Optional[str] = None,
    ) -> None:
        """Mint + store a reset token for ``email`` and email the link.

        Deliberately returns ``None`` on every path — the caller responds
        with the same generic 200 whether or not the account exists, so
        this method never leaks existence. If no active user matches the
        address we simply do nothing.

        Email delivery is best-effort: a send failure is logged and
        swallowed (same posture as ``invite_service.create_invite``), so a
        broken SMTP / SES-sandbox rejection never 500s the endpoint.
        """
        result = await self.db.execute(
            select(User).where(
                User.email == email,
                User.deleted_at.is_(None),
            )
        )
        user = result.scalar_one_or_none()

        # No active account → do nothing, but the endpoint still returns the
        # generic success message. Demo guests have a placeholder password
        # and cannot reset either.
        if user is None or getattr(user, "is_demo", False):
            logger.info("Password reset requested for unknown/ineligible address — no-op")
            return

        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + RESET_TOKEN_TTL
        user.password_reset_token = token
        user.password_reset_expires_at = expires_at
        await self.db.commit()
        await self.db.refresh(user)

        logger.info("✅ Password reset token minted for %s (expires %s)", email, expires_at)

        # Best-effort email — never block the endpoint on delivery.
        try:
            frontend_url = base_url
            if not frontend_url and getattr(settings, "CORS_ORIGINS", None):
                frontend_url = settings.CORS_ORIGINS.split(",")[0].strip()
            if not frontend_url:
                frontend_url = "http://localhost:3000"
            reset_link = f"{frontend_url.rstrip('/')}/login/reset-password?token={token}"
            email_service = EmailService()
            email_service.send_password_reset_email(email, reset_link)
        except Exception:  # pragma: no cover — guard against SMTP outage
            logger.exception("Failed to send password reset email to %s", email)

    async def reset_password(self, token: str, new_password: str) -> User:
        """Consume a reset token and set the user's new password.

        Raises ``BadRequestError`` on an unknown or expired token. On
        success the token + expiry are cleared so it cannot be replayed.
        """
        if not token:
            raise BadRequestError("Invalid or expired reset token")

        result = await self.db.execute(
            select(User).where(
                User.password_reset_token == token,
                User.deleted_at.is_(None),
            )
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise BadRequestError("Invalid or expired reset token")

        # SQLite can hand back naive datetimes; normalize to UTC-aware
        # before comparing (same defensive pattern as invite_service).
        expires_at = user.password_reset_expires_at
        if expires_at is not None and getattr(expires_at, "tzinfo", None) is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at is None or expires_at < datetime.now(timezone.utc):
            raise BadRequestError("Invalid or expired reset token")

        user.password_hash = get_password_hash(new_password)
        user.password_reset_token = None
        user.password_reset_expires_at = None
        await self.db.commit()
        await self.db.refresh(user)

        logger.info("✅ Password reset completed for %s", user.email)
        return user
