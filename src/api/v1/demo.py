"""Public demo signup endpoint — Cenário B (per-visitor sandbox).

POST /demo/signup is the only path a non-authenticated visitor has into
the platform. Anti-fraud is layered: server-side Turnstile verification,
per-IP rate limit, throwaway-email block list.

The endpoint is intentionally NOT mounted behind get_current_user — it
issues the JWT itself.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Request, status
from fastapi.params import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session
from src.api.deps import get_current_user
from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.models.space import Space
from src.models.user import User
from src.schemas.common import ErrorResponse
from src.schemas.demo import DemoSignupRequest, DemoSignupResponse
from src.services.demo_service import DemoService

router = APIRouter()


def _client_ip(request: Request) -> Optional[str]:
    """Extracts the visitor IP, honouring X-Forwarded-For when set by the
    ingress. Returns None when nothing is reachable (used for tests)."""
    fwd = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


@router.post(
    "/signup",
    response_model=DemoSignupResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
    summary="Public demo signup",
    description=(
        "Provisions a per-visitor sandbox (Space + guest user) and returns a "
        "JWT pair. Requires a valid Cloudflare Turnstile token. Rate-limited "
        "per source IP. Returning visitors with the same email get their "
        "existing sandbox re-issued instead of a fresh one."
    ),
)
async def signup(
    payload: DemoSignupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> DemoSignupResponse:
    # Demo is platform-only. Real customer tenants (e.g. gbtsolutions) have
    # ``feature_flags.demo_enabled = false``; the front-end hides the demo
    # link (auth.py show_demo), but this endpoint MUST enforce it too —
    # otherwise anyone can POST /demo/signup and provision a demo Space
    # inside a real tenant (a "Demo Sky" space appeared in gbtsolutions
    # exactly this way: the global settings.DEMO_ENABLED was the only gate).
    # The default/platform context keeps the public demo open.
    ctx = getattr(request.state, "tenant_context", None)
    if ctx is not None and not getattr(ctx, "is_default", False):
        flags = getattr(ctx, "feature_flags", None) or {}
        if not flags.get("demo_enabled", False):
            raise ForbiddenError("Demo is not available on this workspace.")

    service = DemoService(db)
    return await service.signup(
        payload=payload,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


@router.post(
    "/{user_id}/extend",
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
    summary="Extend a demo user's TTL by N days",
    description=(
        "Owner / Admin only. Pushes both the user's `demo_expires_at` and "
        "their demo Space's `demo_expires_at` forward by `days` (default 7). "
        "Idempotent on a single click — the new TTL is `max(now, current_ttl) "
        "+ days` so re-clicking doesn't shrink the window. Lucas's "
        "2026-04-30 brief: 'extend by 7 days do lado da conta do usuario na "
        "tela de settings > member'."
    ),
)
async def extend_demo_user(
    user_id: UUID,
    days: int = 7,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    if current_user.role not in ("owner", "admin", "super_admin"):
        raise ForbiddenError(
            "Only the tenant Owner or an Admin can extend a demo TTL."
        )
    if days <= 0 or days > 90:
        raise BadRequestError("`days` must be between 1 and 90.")

    target = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if target is None or not getattr(target, "is_demo", False):
        raise NotFoundError("Demo user not found.")

    now = datetime.now(timezone.utc)
    base = (
        target.demo_expires_at
        if target.demo_expires_at and target.demo_expires_at > now
        else now
    )
    new_ttl = base + timedelta(days=days)
    target.demo_expires_at = new_ttl

    # The Space the user owns shares the TTL — keep them in sync so the
    # cleanup cron doesn't reap the Space mid-extension.
    space_q = await db.execute(
        select(Space).where(Space.created_by == target.id, Space.is_demo.is_(True))
    )
    space = space_q.scalars().first()
    if space is not None:
        space.demo_expires_at = new_ttl

    await db.commit()

    # audit_events row so the "who extended which user when" is traceable.
    try:
        from src.services.audit_service import AuditService

        await AuditService(db).log_event(
            actor_kind="user",
            actor_id=current_user.id,
            actor_email=current_user.email,
            action="demo.user.extended",
            resource_kind="user",
            resource_id=str(target.id),
            decision="allow",
            decision_reason=f"days={days}",
            metadata={
                "target_email": target.email,
                "new_demo_expires_at": new_ttl.isoformat(),
            },
        )
    except Exception:
        pass

    return {
        "user_id": str(target.id),
        "email": target.email,
        "demo_expires_at": new_ttl.isoformat(),
        "extended_by_days": days,
    }


@router.post(
    "/reseed-space/{space_id}",
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
    summary="Re-run the demo seed on an existing Space",
    description=(
        "Owner / Admin only. Idempotently re-applies every demo seed step "
        "(connections → knowledge → agents → findings) to the supplied "
        "Space. Use this to heal a Space whose Sources / Agents panel "
        "ended up empty because the DEMO_DATASET_CONNECTION_IDS env var "
        "was missing or pointed at stale UUIDs when the visitor signed "
        "up. Each underlying step is idempotent so the action is safe "
        "to retry. Returns the counts of what was added."
    ),
)
async def reseed_space(
    space_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    if current_user.role not in ("owner", "admin", "super_admin"):
        raise ForbiddenError(
            "Only the tenant Owner or an Admin can reseed a demo Space."
        )
    return await DemoService(db).reseed_space(space_id, current_user)
