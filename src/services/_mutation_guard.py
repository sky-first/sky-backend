"""Shared mutation-authorization helper.

Red-team finding HI-002 (2026-04-23): multiple service files
(agent/widget/dashboard/connection/strategy) let any authenticated
user DELETE or UPDATE entities that belonged to someone else — either
in Personal mode (cross-user) or in Space/Crew mode (lower role
deleting a higher role's items).

This module is the single point of enforcement. Every mutation handler
should resolve its entity then call one of:

- :func:`require_personal_owner_or_404` for Personal-scope entities
  (those carrying ``owner_user_id``)
- :func:`require_collaborative_mutation_rights` for Space/Crew
  entities (those carrying ``space_id`` and/or ``crew_id``)
- :func:`require_mutation_rights` — dispatcher that picks one of the
  above based on the entity's fields.

Policy (agreed with product, 2026-04-23):

1. **Personal**: only the ``owner_user_id`` may delete/update. Return
   404 (not 403) so the endpoint does not advertise existence.
2. **Creator bypass** (Space/Crew): the user who *created* the row can
   always delete/update it, regardless of per-space role. An
   viewer who owns a widget can remove their own widget.
3. **Non-creator must clear RBAC**: any other caller needs the
   matching ``<entity>.<action>`` permission in the entity's space —
   this is where role hierarchy kicks in (editor cannot delete,
   owner and platform admin can). We delegate to
   :class:`~src.services.rbac_service.RBACService`.
4. **Platform admins / owners** bypass 2 + 3 entirely — handled inside
   :class:`RBACService` so we don't have to repeat it.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User


def require_personal_owner_or_404(entity: Any, current_user_id: UUID) -> None:
    """Block Personal-scope mutations by anyone but the owner.

    Silent-404 on mismatch (to avoid an existence oracle across users).
    No-op when the entity is not Personal (``owner_user_id is None``);
    the collaborative guard handles those.
    """
    owner = getattr(entity, "owner_user_id", None)
    if owner is not None and owner != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )


async def require_collaborative_mutation_rights(
    entity: Any,
    *,
    user: User,
    rbac_permission: str,
    db: AsyncSession,
) -> None:
    """Enforce creator-bypass + RBAC for a Space/Crew entity.

    - If ``entity.created_by == user.id`` → allow (creator bypass).
    - Else → :class:`RBACService` must say the user has
      ``rbac_permission`` in the entity's space.

    The caller supplies ``rbac_permission`` as the catalog key, e.g.
    ``"widgets.delete"`` / ``"connections.edit"``. See
    :data:`src.services.rbac_service.DEFAULT_ROLE_PERMISSIONS` for the
    role → permission matrix that ultimately decides the answer.
    """
    # Creator bypass first — cheap and matches the product rule.
    created_by = getattr(entity, "created_by", None) or getattr(
        entity, "created_by_id", None
    )
    if created_by and created_by == user.id:
        return

    # Non-creator: RBAC scoped to the entity's space.
    space_id = getattr(entity, "space_id", None)
    from src.services.rbac_service import RBACService

    await RBACService(db).assert_permission(
        user, rbac_permission, space_id=space_id
    )


async def require_mutation_rights(
    entity: Any,
    *,
    user: User,
    rbac_permission: str,
    db: AsyncSession,
) -> None:
    """Dispatcher — picks personal-vs-collaborative by entity shape.

    Order of precedence:
      1. If the entity carries a non-NULL ``owner_user_id`` → Personal
         check only. Creator bypass doesn't apply (the owner IS the
         caller in that mode, or we 404).
      2. Otherwise → collaborative creator-bypass + RBAC.
    """
    if getattr(entity, "owner_user_id", None) is not None:
        require_personal_owner_or_404(entity, user.id)
        return
    await require_collaborative_mutation_rights(
        entity, user=user, rbac_permission=rbac_permission, db=db
    )


def _not_found_if_missing(entity: Optional[Any], label: str) -> None:
    """Helper — most services already load the entity then mutate;
    this centralises the 404 so the caller stays short."""
    if entity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{label} not found",
        )
