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
from src.models.connection import DataConnection
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

    @staticmethod
    def _parse_connection_ids() -> list[UUID]:
        """Resolve the list of dataset connection UUIDs to wire onto a new
        demo Space. Reads DEMO_DATASET_CONNECTION_IDS first (CSV); falls
        back to the legacy DEMO_DATASET_CONNECTION_ID single value.
        Invalid entries are logged and skipped so one bad UUID doesn't
        break the entire signup flow.
        """
        plural = (getattr(settings, "DEMO_DATASET_CONNECTION_IDS", "") or "").strip()
        if plural:
            uuids: list[UUID] = []
            for raw in plural.split(","):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    uuids.append(UUID(raw))
                except (ValueError, TypeError):
                    logger.warning(
                        "DEMO_DATASET_CONNECTION_IDS contains invalid UUID %r — skipping.",
                        raw,
                    )
            return uuids

        singular = (settings.DEMO_DATASET_CONNECTION_ID or "").strip()
        if singular:
            try:
                return [UUID(singular)]
            except (ValueError, TypeError):
                logger.warning(
                    "DEMO_DATASET_CONNECTION_ID is set but not a valid UUID — skipping wire-up."
                )
        return []

    async def _find_sibling_demo_space(self, email_domain: str) -> Optional[Space]:
        """Return the active demo Space whose owner shares ``email_domain``.

        Used by item D (same-domain grouping): the first signup from
        @acme.com mints the Space and becomes commander; later signups
        from @acme.com join that Space instead of creating new ones.

        Returns None if:
          - email_domain is empty
          - no active (TTL not expired) demo Space exists for that domain
          - the only matching Space is owned by the calling user's own row
            (caller's been moved to _issue_returning before reaching here)
        """
        if not email_domain or "." not in email_domain:
            return None

        now = datetime.now(timezone.utc)
        # Match via SQL on User.email LIKE '%@<domain>' joined to
        # Space.created_by. The deleted_at filter on Space is implicit
        # via the demo_expires_at > now check (cron CASCADE-deletes
        # expired sandboxes anyway).
        q = await self.db.execute(
            select(Space)
            .join(User, User.id == Space.created_by)
            .where(
                Space.is_demo.is_(True),
                Space.demo_expires_at > now,
                User.is_demo.is_(True),
                User.email.like(f"%@{email_domain}"),
            )
            .order_by(Space.created_at.asc())  # oldest sibling = canonical
            .limit(1)
        )
        return q.scalar_one_or_none()

    async def _join_sibling_demo_space(
        self,
        *,
        payload: DemoSignupRequest,
        email_norm: str,
        sibling_space: Space,
        client_ip: Optional[str],
    ) -> DemoSignupResponse:
        """Mint a new User and attach them as a navigator of an existing
        same-domain demo Space. Reuses the parent Space's TTL so the
        whole org's sandbox expires together. Logs loudly so the
        lead-gen pipeline can pick the event up.
        """
        # The new visitor's TTL = the sibling Space's TTL (same expiry
        # for the whole company so the sandbox doesn't get split into
        # an awkward "yours expired but theirs didn't" state).
        expires_at = sibling_space.demo_expires_at or (
            datetime.now(timezone.utc) + timedelta(days=max(1, int(settings.DEMO_TTL_DAYS)))
        )

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
                "demo_joined_existing_space": str(sibling_space.id),
            },
        )
        self.db.add(user)
        await self.db.flush()

        # Navigator role: full content writes (dashboards, widgets,
        # agents, AI) but cannot manage members, edit Space settings,
        # or delete crews. Owner of the demo Space can promote them
        # via the standard members endpoint.
        self.db.add(SpaceMember(
            id=uuid4(),
            space_id=sibling_space.id,
            user_id=user.id,
            role="navigator",
        ))

        await self.db.commit()
        await self.db.refresh(user)
        await self.db.refresh(sibling_space)

        logger.info(
            "demo_same_domain_join space_id=%s owner_id=%s new_user_id=%s "
            "email=%s domain=%s",
            sibling_space.id, sibling_space.created_by, user.id,
            email_norm, email_norm.split("@", 1)[1],
        )

        return self._issue_response(
            user, sibling_space, expires_at, is_returning=False,
        )

    async def _ensure_dataset_connections(self, space: Space) -> int:
        """Idempotently bind the configured demo dataset connections to ``space``.

        Reads ``DEMO_DATASET_CONNECTION_IDS`` (or the legacy singular)
        and, for each UUID that:
          (a) exists as a row in ``data_connections`` (so the FK insert
              won't 23503 on us), and
          (b) is not already bridged to this Space,
        adds a ``SpaceConnection`` row. Missing UUIDs are logged loudly
        — operationally that means the seed script wasn't run against
        this DB, or the env var was edited and points at a stale ID.

        Returns the number of rows added (0 on a no-op).

        Called from both ``_issue_new`` (initial provision) and
        ``_issue_returning`` (backfill for Spaces created before the env
        var was deployed). The session is NOT committed here — caller
        commits as part of its own transaction.
        """
        wanted = self._parse_connection_ids()
        if not wanted:
            return 0

        # 1. Filter to UUIDs that actually exist in data_connections.
        existing_q = await self.db.execute(
            select(DataConnection.id).where(DataConnection.id.in_(wanted))
        )
        existing_ids: set[UUID] = {row for row in existing_q.scalars().all()}
        missing = [str(u) for u in wanted if u not in existing_ids]
        if missing:
            logger.warning(
                "demo_dataset_connection_ids reference missing data_connections "
                "rows — these IDs will be skipped. Did the seed script run "
                "against this DB? missing=%s",
                missing,
            )
        if not existing_ids:
            return 0

        # 2. Skip the ones already bound to avoid duplicate-key errors.
        already_q = await self.db.execute(
            select(SpaceConnection.connection_id).where(
                SpaceConnection.space_id == space.id,
                SpaceConnection.connection_id.in_(existing_ids),
            )
        )
        already: set[UUID] = {row for row in already_q.scalars().all()}

        added = 0
        for conn_uuid in existing_ids:
            if conn_uuid in already:
                continue
            self.db.add(SpaceConnection(space_id=space.id, connection_id=conn_uuid))
            added += 1

        if added:
            logger.info(
                "demo_space_connections_bound space_id=%s added=%d total_wanted=%d",
                space.id, added, len(wanted),
            )
        return added

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
        email_domain = email_norm.split("@", 1)[1] if "@" in email_norm else ""

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

        # Same-domain grouping (D): a colleague from the same company
        # already has a demo sandbox? Bind this new user as a member of
        # the SAME Space instead of creating a new one. Pre-A1 behavior
        # was "every email = new sandbox" which fragmented teams across
        # parallel demos and made the same-org collaboration story
        # impossible. Now: first signup mints the Space + becomes
        # commander; subsequent same-domain signups join as navigator
        # (full content access, no member/space/connection management).
        # Owner can promote later if needed.
        sibling_space = await self._find_sibling_demo_space(email_domain)
        if sibling_space is not None:
            return await self._join_sibling_demo_space(
                payload=payload,
                email_norm=email_norm,
                sibling_space=sibling_space,
                client_ip=client_ip,
            )

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

        # Member bridge — guest is COMMANDER of their own sandbox so
        # the BE rbac_service.py:1014 path matches commander/navigator/
        # explorer and grants the full Space-axis capabilities. Earlier
        # demo signups used role="admin" which fell through to "guest"
        # because that match-list is strict — that's why every demo
        # tester before A1 hit "no permission to run queries" the first
        # time they tried the AI. See test_rbac_space_role_axis.py:S-80.
        member = SpaceMember(
            id=uuid4(),
            space_id=space.id,
            user_id=user.id,
            role="commander",
        )
        self.db.add(member)

        # Optional shared dataset connections. Two env vars are supported,
        # in this order:
        #   1. DEMO_DATASET_CONNECTION_IDS (comma-separated list) — wires
        #      every UUID in the list to the new Space. This is what the
        #      multi-schema synthetic dataset uses (CRM, Marketing,
        #      Finance, Web Analytics, Product Usage = 5 connections).
        #   2. DEMO_DATASET_CONNECTION_ID (single UUID, legacy) — kept
        #      for backwards compatibility with the original single-DB
        #      design. Used only when the plural is empty.
        # When both are empty the Space starts with no data — still valid
        # for click-the-buttons demos.
        await self._ensure_dataset_connections(space)

        await self.db.commit()
        await self.db.refresh(user)
        await self.db.refresh(space)

        # Welcome email (Resend) — sent ONLY on fresh cold signups.
        # Returning visitors don't get another welcome (already sent
        # the first time), and same-domain joiners get a different
        # template (TODO: separate "your colleague invited you" mail).
        # Fire-and-forget: failures are logged inside the helper so a
        # vendor outage can't roll back the sandbox.
        from src.services.demo_email_service import send_demo_welcome_email
        await send_demo_welcome_email(
            name=user.name,
            email=user.email,
            company=payload.company,
            expires_at=expires_at,
        )

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

        # Backfill #1: a returning visitor whose Space was provisioned
        # before DEMO_DATASET_CONNECTION_IDS was set ends up with an
        # empty Space — the idempotent binder closes that gap without
        # a one-shot migration script.
        added = await self._ensure_dataset_connections(space)

        # Backfill #2 (A1): pre-A1 signups created SpaceMember.role=
        # "admin", which falls through to "guest" in rbac_service:1014
        # (match-list is commander/navigator/explorer). Normalize any
        # legacy row on every returning login — idempotent, no-op when
        # already correct. Also handles legacy "member" → "explorer".
        normalized = await self._normalize_legacy_member_role(space, user)

        if added or normalized:
            await self.db.commit()

        return self._issue_response(
            user,
            space,
            user.demo_expires_at or datetime.now(timezone.utc),
            is_returning=True,
        )

    async def _normalize_legacy_member_role(
        self, space: Space, user: User,
    ) -> bool:
        """Convert SpaceMember.role from legacy admin/member to
        commander/explorer for this user/space pair. Returns True if
        a row was actually mutated (caller should commit), False
        otherwise.
        """
        res = await self.db.execute(
            select(SpaceMember).where(
                SpaceMember.space_id == space.id,
                SpaceMember.user_id == user.id,
            )
        )
        member = res.scalar_one_or_none()
        if member is None:
            return False

        legacy_to_canonical = {"admin": "commander", "member": "explorer"}
        new_role = legacy_to_canonical.get(member.role)
        if new_role is None:
            return False  # already commander/navigator/explorer or unknown

        logger.info(
            "demo_legacy_role_normalized space_id=%s user_id=%s "
            "from=%s to=%s",
            space.id, user.id, member.role, new_role,
        )
        member.role = new_role
        return True

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
