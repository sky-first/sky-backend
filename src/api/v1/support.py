"""Sky Support JIT endpoints — manage support access and sessions."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.core.exceptions import ForbiddenError, NotFoundError
from src.models.user import User
from src.schemas.common import SuccessResponse

router = APIRouter()


# --- Schemas ---

class SupportSettingsResponse(BaseModel):
    access_enabled: bool
    require_ticket_id: bool
    allowed_modes: list
    auto_revoke_after_minutes: int


class SupportSettingsUpdate(BaseModel):
    access_enabled: Optional[bool] = None
    require_ticket_id: Optional[bool] = None
    auto_revoke_after_minutes: Optional[int] = None


class SupportSessionCreate(BaseModel):
    ticket_id: Optional[str] = None
    mode: str = "read_only"
    justification: Optional[str] = None


class SupportSessionResponse(BaseModel):
    id: str
    mode: str
    ticket_id: Optional[str] = None
    started_at: str
    expires_at: str


# --- Endpoints ---

@router.get(
    "/settings",
    status_code=status.HTTP_200_OK,
    summary="Get support settings",
)
async def get_support_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Get current Sky Support settings. Admin only."""
    if current_user.role not in ("admin", "owner", "super_admin"):
        raise ForbiddenError("Support settings require admin role")

    from sqlalchemy import text
    result = await db.execute(text("SELECT access_enabled, require_ticket_id, allowed_modes, auto_revoke_after_minutes FROM support_settings LIMIT 1"))
    row = result.fetchone()
    if not row:
        return {"access_enabled": True, "require_ticket_id": False, "allowed_modes": ["read_only"], "auto_revoke_after_minutes": 240}
    return {
        "access_enabled": row[0],
        "require_ticket_id": row[1],
        "allowed_modes": row[2] or ["read_only"],
        "auto_revoke_after_minutes": row[3],
    }


@router.put(
    "/settings",
    status_code=status.HTTP_200_OK,
    summary="Update support settings",
)
async def update_support_settings(
    settings_data: SupportSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Update Sky Support settings. Admin only. Sky operators cannot change this."""
    if current_user.role not in ("admin", "owner", "super_admin"):
        raise ForbiddenError("Support settings require admin role")

    # Sky operators cannot disable support toggle (they can't lock customers out)
    if getattr(current_user, "is_sky_operator", False):
        raise ForbiddenError("Sky operators cannot modify support settings")

    from sqlalchemy import text
    updates = {}
    if settings_data.access_enabled is not None:
        updates["access_enabled"] = settings_data.access_enabled
    if settings_data.require_ticket_id is not None:
        updates["require_ticket_id"] = settings_data.require_ticket_id
    if settings_data.auto_revoke_after_minutes is not None:
        updates["auto_revoke_after_minutes"] = settings_data.auto_revoke_after_minutes

    if updates:
        set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
        updates["now"] = datetime.now(timezone.utc)
        await db.execute(text(f"UPDATE support_settings SET {set_clauses}, updated_at = :now"), updates)
        await db.commit()

    return await get_support_settings(current_user, db)


@router.post(
    "/sessions",
    status_code=status.HTTP_201_CREATED,
    summary="Create JIT support session",
)
async def create_support_session(
    session_data: SupportSessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Create a JIT support session. Requires support access to be enabled."""
    # Check if support access is enabled
    from sqlalchemy import text
    settings_row = await db.execute(text("SELECT access_enabled, require_ticket_id, auto_revoke_after_minutes FROM support_settings LIMIT 1"))
    settings = settings_row.fetchone()

    if not settings or not settings[0]:
        raise ForbiddenError("Sky Support access is disabled by the customer")

    if settings[1] and not session_data.ticket_id:
        raise ForbiddenError("A ticket ID is required for support sessions")

    ttl = settings[2] or 240
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=ttl)

    result = await db.execute(text("""
        INSERT INTO support_sessions (operator_id, ticket_id, mode, justification, expires_at)
        VALUES (:op_id, :ticket, :mode, :justification, :expires)
        RETURNING id, started_at
    """), {
        "op_id": current_user.id,
        "ticket": session_data.ticket_id,
        "mode": session_data.mode,
        "justification": session_data.justification,
        "expires": expires,
    })
    row = result.fetchone()
    await db.commit()

    return {
        "id": str(row[0]),
        "session_id": str(row[0]),
        "mode": session_data.mode,
        "ticket_id": session_data.ticket_id,
        "started_at": row[1].isoformat(),
        "expires_at": expires.isoformat(),
    }


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_200_OK,
    summary="Revoke a support session",
)
async def revoke_support_session(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """Customer admin can revoke a support session immediately."""
    if current_user.role not in ("admin", "owner", "super_admin"):
        raise ForbiddenError("Only admin can revoke support sessions")

    from sqlalchemy import text
    result = await db.execute(text("""
        UPDATE support_sessions SET revoked_at = :now, revoked_by = :by
        WHERE id = :sid AND revoked_at IS NULL
    """), {
        "now": datetime.now(timezone.utc),
        "by": current_user.id,
        "sid": session_id,
    })
    await db.commit()

    if result.rowcount == 0:
        raise NotFoundError("Session not found or already revoked")

    return SuccessResponse(message="Support session revoked")
