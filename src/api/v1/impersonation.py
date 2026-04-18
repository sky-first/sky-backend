"""
User impersonation endpoints (ADR-001 Fase 2).

POST /users/{user_id}/impersonate
POST /users/me/impersonate/exit

Invariants enforced (matching tests/backend/21-permissions-rbac/19-impersonation-audit/):
  - users.impersonate permission required (default False for every role)
  - max session = 60 minutes, floor = 1 minute
  - every action gets on_behalf_of in the session token
  - every start/exit is audit-logged
  - target user receives a notification (TODO: wire via notifications service)
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.security import create_access_token
from src.models.user import User
from src.schemas.impersonation import (
    ImpersonationExitResponse,
    ImpersonationSessionResponse,
    ImpersonationStartRequest,
)
from src.services.audit_service import AuditService
from src.services.rbac_service import RBACService

router = APIRouter()


MAX_IMPERSONATION_MINUTES = 60


@router.post(
    "/{user_id}/impersonate",
    response_model=ImpersonationSessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Start impersonation session",
    description=(
        "Issue an impersonation token for the target user. Requires the "
        "`users.impersonate` permission. Maximum session duration is 60 minutes. "
        "Every action during impersonation carries `on_behalf_of` in the JWT."
    ),
)
async def start_impersonation(
    user_id: UUID,
    body: ImpersonationStartRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ImpersonationSessionResponse:
    # RBAC gate — default deny for everyone; must be granted explicitly.
    await RBACService(db).assert_permission(current_user, "users.impersonate")

    # Cannot impersonate yourself (no-op + potential audit noise).
    if current_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot impersonate yourself.",
        )

    # Validate target exists.
    target_result = await db.execute(select(User).where(User.id == user_id))
    target = target_result.scalar_one_or_none()
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target user not found",
        )

    # Clamp max_minutes to the hard cap; Pydantic already constrains 1-60,
    # but we defensively re-clamp so a schema change can't accidentally
    # widen the window without code review here.
    max_minutes = min(max(body.max_minutes, 1), MAX_IMPERSONATION_MINUTES)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=max_minutes)

    # Build the impersonation token. Subject is the TARGET user so downstream
    # authz decisions run as them. `on_behalf_of` marks who actually triggered
    # the session — audit log and downstream services use this to trace back
    # to the real admin.
    token = create_access_token(
        data={
            "sub": str(target.id),
            "on_behalf_of": str(current_user.id),
            "impersonation": True,
            "mode": body.mode,
        },
        expires_delta=timedelta(minutes=max_minutes),
    )

    # Audit log.
    await AuditService(db).log_event(
        actor_kind="user",
        actor_id=current_user.id,
        actor_email=current_user.email,
        action="impersonation.start",
        resource_kind="user",
        resource_id=str(target.id),
        decision="allow",
        decision_reason=body.reason,
        metadata={
            "mode": body.mode,
            "max_minutes": max_minutes,
            "expires_at": expires_at.isoformat(),
        },
    )

    # TODO: fire notification to target (invariant B21.19.5) when the
    # notifications service gains an impersonation_started channel.

    await db.commit()

    return ImpersonationSessionResponse(
        session_token=token,
        on_behalf_of=str(target.id),
        expires_at=expires_at,
        mode=body.mode,
    )


@router.post(
    "/me/impersonate/exit",
    response_model=ImpersonationExitResponse,
    status_code=status.HTTP_200_OK,
    summary="End current impersonation session",
)
async def exit_impersonation(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ImpersonationExitResponse:
    # The client is responsible for discarding the impersonation token and
    # reverting to the admin's original token. Server-side we just audit
    # the exit. If a revocation list is later added (session blocklist),
    # that's where the token-kill would happen.
    now = datetime.now(timezone.utc)
    await AuditService(db).log_event(
        actor_kind="user",
        actor_id=current_user.id,
        actor_email=current_user.email,
        action="impersonation.exit",
        resource_kind="user",
        resource_id=str(current_user.id),
        decision="allow",
    )
    await db.commit()
    return ImpersonationExitResponse(message="Impersonation session ended", ended_at=now)
