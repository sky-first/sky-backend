"""Shared RBAC guards for platform-level endpoints.

Centralizes the `role in (admin, owner)` check so a one-shot rename
or policy change touches one spot instead of 40 endpoints.
"""

from fastapi import Depends

from src.api.deps import get_current_user
from src.core.exceptions import ForbiddenError
from src.models.user import User


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency — enforces platform admin or owner.

    Usage:
        @router.get("/admin-stuff", ..., dependencies=[Depends(require_admin)])
    or as a positional dep to also get the user:
        async def handler(user: User = Depends(require_admin)): ...
    """
    role = (getattr(current_user, "role", None) or "").lower()
    if role not in {"admin", "owner", "superadmin"}:
        raise ForbiddenError("Administrator role required.")
    return current_user


def require_owner(current_user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency — enforces platform owner only.

    For billing, tenant-delete, DSAR, ownership transfer.
    """
    role = (getattr(current_user, "role", None) or "").lower()
    if role != "owner":
        raise ForbiddenError("Owner role required.")
    return current_user
