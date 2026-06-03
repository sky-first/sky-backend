"""Audit endpoints — read-only access to the immutable audit log."""

from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.services.audit_service import AuditService
from src.services.rbac_service import RBACService

router = APIRouter()


@router.get(
    "/",
    status_code=status.HTTP_200_OK,
    summary="List audit events",
    description="Paginated list of audit events. Requires admin role.",
)
async def list_audit_events(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    action: Optional[str] = Query(None),
    actor_kind: Optional[str] = Query(None),
    decision: Optional[str] = Query(None),
    resource_kind: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """List audit events with optional filters."""
    if current_user.role not in ("admin", "owner", "super_admin"):
        from src.core.exceptions import ForbiddenError

        raise ForbiddenError("Audit log access requires admin role")

    audit = AuditService(db)
    return await audit.list_events(
        limit=limit,
        offset=offset,
        action=action,
        actor_kind=actor_kind,
        decision=decision,
        resource_kind=resource_kind,
    )


# Back-compat alias — /audit-logs/events (or /audit/events via the legacy
# mount) still works for any pre-existing caller.
router.add_api_route(
    "/events",
    list_audit_events,
    methods=["GET"],
    include_in_schema=False,
)


@router.get(
    "/verify",
    status_code=status.HTTP_200_OK,
    summary="Verify audit chain integrity",
    description="Check the hash chain for tampering.",
)
async def verify_audit_chain(
    limit: int = Query(1000, ge=1, le=10000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Verify audit log hash chain integrity."""
    if current_user.role not in ("admin", "owner", "super_admin"):
        from src.core.exceptions import ForbiddenError

        raise ForbiddenError("Audit chain verification requires admin role")

    audit = AuditService(db)
    return await audit.verify_chain(limit=limit)
