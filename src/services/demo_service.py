"""Public demo (Cenário B) service.

Provisions a per-visitor sandbox: a User, a Space marked is_demo with
a TTL, a SpaceMember bridge, optional shared dataset Connection, and
issues a normal JWT pair so the FE behaves the same as for an SSO
login. Cleans up expired sandboxes via cleanup_expired_demo_spaces().

Anti-fraud:
  • Cloudflare Turnstile token verified server-side
  • Per-IP signup rate limit (Redis with in-memory fallback)
  • Throwaway email block list (validated in DemoSignupRequest)
  • Returning visitors with the same email get their existing sandbox
    instead of a fresh one — avoids brute-force volume
"""

from __future__ import annotations

import logging
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from uuid import UUID, uuid4

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.core.exceptions import BadRequestError, ForbiddenError
from src.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
)
from src.models.space import Space, SpaceConnection, SpaceMember
from src.models.user import User
from src.schemas.demo import DemoSignupRequest, DemoSignupResponse
from src.schemas.user import UserResponse

logger = logging.getLogger(__name__)


# ─── Per-IP signup rate limit (Redis if available, memory otherwise) ────────

# In-memory fallback: keyed by IP, holds a list of timestamps. Cleared
# implicitly when entries fall outside the rolling window.
_IP_SIGNUP_HITS: dict[str, list[float]] = defaultdict(list)


def _check_ip_rate_limit(ip: str, limit: int, window_seconds: int = 3600) -> bool:
    """True if under-limit, False if the IP has already hit `limit` signups
    in the trailing `window_seconds`.

    Uses Redis when configured, falls back to a process-local dict otherwise.
    """
    if not ip:
        # Unknown IP — fail-closed for safety.
        return False

    # Redis path
    try:
        import redis  # type: ignore

        if settings.REDIS_URL:
            r = redis.from_url(settings.REDIS_URL, decode_responses=True, socket_timeout=1)
            key = f"demo:signup:ip:{ip}"
            count = r.incr(key)
            if count == 1:
                r.expire(key, window_seconds)
            return int(count) <= limit
    except Exception as exc:  # pragma: no cover — only triggers in dev/no-redis
        logger.debug("demo rate limit Redis unavailable, falling back: %s", exc)

    # Memory fallback
    now = time.time()
    cutoff = now - window_seconds
    hits = [t for t in _IP_SIGNUP_HITS[ip] if t >= cutoff]
    hits.append(now)
    _IP_SIGNUP_HITS[ip] = hits
    return len(hits) <= limit


# ─── Cloudflare Turnstile ───────────────────────────────────────────────────


def _parse_connection_ids() -> list[UUID]:
    """Reads DEMO_DATASET_CONNECTION_IDS (comma-sep UUIDs) and falls
    back to the legacy single DEMO_DATASET_CONNECTION_ID. Skips entries
    that aren't valid UUIDs with a warning so a typo in env doesn't
    crash signup."""
    raw_list = settings.DEMO_DATASET_CONNECTION_IDS or settings.DEMO_DATASET_CONNECTION_ID or ""
    out: list[UUID] = []
    for token in raw_list.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            out.append(UUID(token))
        except (ValueError, TypeError):
            logger.warning("Skipping invalid demo connection id: %s", token)
    return out


async def _verify_turnstile(token: str, remoteip: Optional[str]) -> bool:
    """Calls Cloudflare's siteverify. Returns True on a valid token."""
    secret = settings.TURNSTILE_SECRET_KEY
    if not secret:
        # In dev / test we skip verification but log it loudly so a
        # forgotten env in production doesn't silently allow bots through.
        logger.warning(
            "TURNSTILE_SECRET_KEY is empty — captcha verification skipped. "
            "DO NOT deploy demo to public internet without setting it."
        )
        return True

    payload = {"secret": secret, "response": token}
    if remoteip:
        payload["remoteip"] = remoteip

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(settings.TURNSTILE_VERIFY_URL, data=payload)
            if resp.status_code != 200:
                logger.warning("Turnstile siteverify HTTP %s", resp.status_code)
                return False
            data = resp.json()
            return bool(data.get("success"))
    except Exception as exc:
        logger.warning("Turnstile siteverify failed: %s", exc)
        return False


# ─── Signup ─────────────────────────────────────────────────────────────────


class DemoService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def signup(
        self,
        payload: DemoSignupRequest,
        client_ip: Optional[str],
        user_agent: Optional[str] = None,
    ) -> DemoSignupResponse:
        if not settings.DEMO_ENABLED:
            raise ForbiddenError("Public demo is currently disabled.")

        ok = _check_ip_rate_limit(
            ip=client_ip or "unknown",
            limit=settings.DEMO_RATE_LIMIT_PER_IP_PER_HOUR,
        )
        if not ok:
            raise BadRequestError(
                "Too many signups from this network in the last hour. Try again later."
            )

        captcha_ok = await _verify_turnstile(payload.turnstile_token, client_ip)
        if not captcha_ok:
            raise BadRequestError("Captcha verification failed. Please refresh and try again.")

        email_norm = payload.email.lower().strip()

        # Returning visitor: same email → return their existing sandbox.
        existing = await self.db.execute(select(User).where(User.email == email_norm))
        existing_user: Optional[User] = existing.scalar_one_or_none()
        if existing_user is not None:
            if not existing_user.is_demo:
                # Email is already a real (SSO) user — refuse to mint a
                # demo sandbox under a real account.
                raise BadRequestError(
                    "This email is already registered. Please sign in via SSO instead."
                )
            return await self._issue_returning(existing_user, user_agent, client_ip)

        # Fresh sandbox.
        ttl_days = max(1, int(settings.DEMO_TTL_DAYS))
        expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)

        # User row — random placeholder password so /auth/login refuses
        # this account (only the demo JWT works).
        user = User(
            id=uuid4(),
            email=email_norm,
            password_hash=get_password_hash(secrets.token_urlsafe(32)),
            name=payload.name,
            role="user",
            email_verified=True,
            is_demo=True,
            demo_expires_at=expires_at,
            preferences={
                "demo_company": payload.company,
                "demo_role": payload.role or "",
                "demo_signup_ip": client_ip or "",
            },
        )
        self.db.add(user)
        await self.db.flush()

        # Space — owned by the demo user, marked is_demo with same TTL.
        space = Space(
            id=uuid4(),
            name=f"Demo — {payload.company}"[:255],
            description="Public demo sandbox. Auto-deleted after the TTL expires.",
            privacy="private",
            sensitivity="internal",
            created_by=user.id,
            is_demo=True,
            demo_expires_at=expires_at,
        )
        self.db.add(space)
        await self.db.flush()

        # Member bridge — guest is admin of their own sandbox so they
        # can do every product action without RBAC blocking the experience.
        member = SpaceMember(
            id=uuid4(),
            space_id=space.id,
            user_id=user.id,
            role="admin",
        )
        self.db.add(member)

        # Wire up the shared read-only demo connections. Each row in
        # DEMO_DATASET_CONNECTION_IDS is a Connection UUID pointing at a
        # different schema in the demo Postgres (crm, marketing, finance,
        # web_analytics, product_usage). Empty list = empty Space, still
        # valid for click-the-buttons demos.
        for conn_uuid in _parse_connection_ids():
            self.db.add(SpaceConnection(space_id=space.id, connection_id=conn_uuid))

        await self.db.commit()
        await self.db.refresh(user)
        await self.db.refresh(space)

        return self._issue_response(user, space, expires_at, is_returning=False)

    async def _issue_returning(
        self,
        user: User,
        user_agent: Optional[str],
        client_ip: Optional[str],
    ) -> DemoSignupResponse:
        """Same email already had a sandbox — find it and re-issue tokens."""
        space_q = await self.db.execute(
            select(Space).where(Space.created_by == user.id, Space.is_demo.is_(True))
        )
        space = space_q.scalars().first()
        if space is None:
            # Edge case: user row exists but Space was already cleaned up
            # by the cron. Kill the orphan user so the next signup mints
            # a fresh sandbox cleanly.
            await self.db.execute(delete(User).where(User.id == user.id))
            await self.db.commit()
            raise BadRequestError(
                "Your previous demo expired. Please submit the form again to get a new sandbox."
            )
        return self._issue_response(
            user,
            space,
            user.demo_expires_at or datetime.now(timezone.utc),
            is_returning=True,
        )

    def _issue_response(
        self,
        user: User,
        space: Space,
        expires_at: datetime,
        *,
        is_returning: bool,
    ) -> DemoSignupResponse:
        token_payload = {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role,
            "demo": True,
            "space_id": str(space.id),
        }
        access_token = create_access_token(token_payload)
        refresh_token = create_refresh_token(token_payload)

        return DemoSignupResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
            user=UserResponse.model_validate(user, from_attributes=True),
            space_id=str(space.id),
            demo_expires_at=expires_at.isoformat(),
            is_returning=is_returning,
        )


# ─── Cron: cleanup ──────────────────────────────────────────────────────────


async def cleanup_expired_demo_spaces(db: AsyncSession) -> Tuple[int, int]:
    """Deletes demo Spaces (and their guest Users) past their TTL.

    Spaces cascade-delete their members, dashboards, widgets, chats by
    the FK setup. Users are owned by themselves so they need a separate
    delete pass once their Space is gone.

    Returns ``(spaces_deleted, users_deleted)``.
    """
    now = datetime.now(timezone.utc)

    # Delete expired Spaces first — FK cascades clean up nested rows.
    expired_spaces_q = await db.execute(
        select(Space.id).where(
            Space.is_demo.is_(True),
            Space.demo_expires_at.is_not(None),
            Space.demo_expires_at < now,
        )
    )
    space_ids = [row[0] for row in expired_spaces_q.all()]
    spaces_deleted = 0
    if space_ids:
        await db.execute(delete(Space).where(Space.id.in_(space_ids)))
        spaces_deleted = len(space_ids)

    # Delete expired guest users (regardless of whether their Space
    # still exists — covers orphans).
    expired_users_q = await db.execute(
        select(User.id).where(
            User.is_demo.is_(True),
            User.demo_expires_at.is_not(None),
            User.demo_expires_at < now,
        )
    )
    user_ids = [row[0] for row in expired_users_q.all()]
    users_deleted = 0
    if user_ids:
        await db.execute(delete(User).where(User.id.in_(user_ids)))
        users_deleted = len(user_ids)

    await db.commit()
    logger.info(
        "demo cleanup pass: spaces=%d users=%d (now=%s)",
        spaces_deleted,
        users_deleted,
        now.isoformat(),
    )
    return spaces_deleted, users_deleted
