"""RBAC service (effective permissions + enforcement).

This is the backend "source of truth" for RBAC. Frontend gating (Subtask 3) is
best-effort UX; this service makes the rules actually enforceable.

Phase 0 RBAC governance (2026-04-09):
    The historical platform-admin "bypass" on lines 131 and 165 below was
    silent — it short-circuited every permission check with no audit trail.
    Per docs/architecture/RBAC_GOVERNANCE_PLAN.md (sky-poc-infra), that
    bypass becomes the integration point for the future Sky Support JIT
    consent flow. Until that flow ships:

    1. Customer admins (`user.role == "admin"`) keep their bypass to avoid
       breaking running deploys, BUT every bypass is now logged so the gap
       is observable in our existing application logs.
    2. Any future user with `is_sky_operator=True` (a column we will add in
       the Sky Support JIT migration) is rejected unless an active JIT
       session is attached. The check is in place now so that adding the
       column later does not require touching this file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError
from src.models.user import User
from src.repositories.connection import ConnectionRepository
from src.repositories.crew import CrewMemberRepository
from src.repositories.permission import PermissionRepository, RolePermissionRepository

logger = logging.getLogger(__name__)


async def _is_sky_operator_without_jit(user: User, db: AsyncSession) -> bool:
    """Reject Sky operators that lack an active JIT consent session.

    Checks the `support_sessions` table for an active (non-revoked, non-expired)
    session for this operator. If none found, they are blocked.
    """
    if not getattr(user, "is_sky_operator", False):
        return False

    # Check for active JIT session in the database
    try:
        from datetime import datetime, timezone

        from sqlalchemy import text

        result = await db.execute(
            text("""
                SELECT id FROM support_sessions
                WHERE operator_id = :uid
                AND revoked_at IS NULL
                AND expires_at > :now
                LIMIT 1
            """),
            {"uid": user.id, "now": datetime.now(timezone.utc)},
        )
        has_active_session = result.scalar_one_or_none() is not None
        return not has_active_session
    except Exception:
        # If support_sessions doesn't exist yet, fall back to denying
        return True

CrewRole = str  # commander | navigator | explorer | guest

ROLE_PRECEDENCE: Dict[str, int] = {
    "guest": 0,
    "explorer": 1,
    "navigator": 2,
    "commander": 3,
}


DEFAULT_ROLE_PERMISSIONS: Dict[str, Dict[str, bool]] = {
    "commander": {
        "createPages": True,
        "viewPages": True,
        "editPages": True,
        "deletePages": True,
        "sharePages": True,
        "manageCrew": True,
        "viewConnections": True,
        "manageConnections": True,
        "connections.edit": True,
        "data.query.run": True,
        "data.table.read": True,
        "admin.users.manage": False,
        "spaces.create": True,
        "spaces.members.manage": True,
        "crews.create": True,
        "crews.members.manage": True,
    },
    "navigator": {
        "createPages": True,
        "viewPages": True,
        "editPages": True,
        "deletePages": False,
        "sharePages": True,
        "manageCrew": False,
        "viewConnections": True,
        "manageConnections": False,
        "connections.edit": True,
        "data.query.run": True,
        "data.table.read": True,
        "admin.users.manage": False,
        "spaces.create": True,
        "spaces.members.manage": True,
        "crews.create": True,
        "crews.members.manage": True,
    },
    "explorer": {
        "createPages": False,
        "viewPages": True,
        "editPages": False,
        "deletePages": False,
        "sharePages": False,
        "manageCrew": False,
        "viewConnections": True,
        "manageConnections": False,
        "connections.edit": False,
        "data.query.run": False,
        "data.table.read": True,
        "admin.users.manage": False,
        "spaces.create": False,
        "spaces.members.manage": False,
        "crews.create": False,
        "crews.members.manage": False,
    },
    "guest": {
        "createPages": False,
        "viewPages": True,
        "editPages": False,
        "deletePages": False,
        "sharePages": False,
        "manageCrew": False,
        "viewConnections": False,
        "manageConnections": False,
        "connections.edit": False,
        "data.query.run": False,
        "data.table.read": False,
        "admin.users.manage": False,
        "spaces.create": False,
        "spaces.members.manage": False,
        "crews.create": False,
        "crews.members.manage": False,
    },
}


@dataclass(frozen=True)
class EffectivePermissions:
    platform_role: str
    crew_role: str
    permissions: Dict[str, bool]


class RBACService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.crew_members = CrewMemberRepository(db)
        self.role_perms = RolePermissionRepository(db)
        self.connection_repo = ConnectionRepository(db)
        self.connection_perms = PermissionRepository(db)

    async def get_effective_permissions(
        self,
        user: User,
        *,
        crew_id: Optional[UUID] = None,
        space_id: Optional[UUID] = None,
        connection_id: Optional[UUID] = None,
    ) -> EffectivePermissions:
        # Sky operator without active JIT session: deny everything (Phase 0
        # forward-compatible guard rail; columns ship in the JIT migration).
        if await _is_sky_operator_without_jit(user, self.db):
            logger.warning(
                "rbac.deny_sky_operator_no_jit user_id=%s",
                getattr(user, "id", None),
            )
            return EffectivePermissions(
                platform_role=user.role or "sky_support",
                crew_role="guest",
                permissions={},
            )

        # Customer admins bypass crew-level checks. This is the temporary
        # behavior — the Sky Support JIT migration replaces this with the
        # consent flow. Until then, log the bypass so operators can audit
        # post-hoc via application logs.
        if user.role == "admin":
            logger.info(
                "rbac.admin_bypass.effective_permissions user_id=%s crew_id=%s space_id=%s connection_id=%s",
                getattr(user, "id", None),
                crew_id,
                space_id,
                connection_id,
            )
            # Return a merged map where known keys are True (unknown keys handled as True by enforcement).
            merged = {}
            for role_map in DEFAULT_ROLE_PERMISSIONS.values():
                merged.update({k: True for k in role_map.keys()})
            return EffectivePermissions(
                platform_role="admin", crew_role="commander", permissions=merged
            )

        crew_role = await self._resolve_context_crew_role(
            user.id, crew_id=crew_id, space_id=space_id, connection_id=connection_id
        )

        defaults = DEFAULT_ROLE_PERMISSIONS.get(crew_role, DEFAULT_ROLE_PERMISSIONS["guest"])
        db_role = await self.role_perms.get_by_role(crew_role)
        merged = {
            **defaults,
            **(db_role.permissions if db_role and db_role.permissions else {}),
        }

        return EffectivePermissions(
            platform_role=user.role, crew_role=crew_role, permissions=merged
        )

    async def _audit_decision(
        self,
        user: User,
        permission_key: str,
        decision: str,
        reason: str,
        resource_kind: Optional[str] = None,
        resource_id: Optional[str] = None,
    ) -> None:
        """Fire-and-forget audit log write. Never blocks the request."""
        try:
            from src.services.audit_service import AuditService

            audit = AuditService(self.db)
            await audit.log_event(
                actor_kind="sky_support" if getattr(user, "is_sky_operator", False) else "user",
                actor_id=getattr(user, "id", None),
                actor_email=getattr(user, "email", None),
                action=permission_key,
                resource_kind=resource_kind,
                resource_id=resource_id,
                decision=decision,
                decision_reason=reason,
            )
        except Exception as exc:
            logger.debug("audit.write_skipped action=%s error=%s", permission_key, exc)

    async def assert_permission(
        self,
        user: User,
        permission_key: str,
        *,
        crew_id: Optional[UUID] = None,
        space_id: Optional[UUID] = None,
        connection_id: Optional[UUID] = None,
    ) -> None:
        resource_id = str(crew_id or space_id or connection_id or "")

        # Sky operator without active JIT session: hard deny.
        if await _is_sky_operator_without_jit(user, self.db):
            await self._audit_decision(user, permission_key, "deny", "sky_support_no_jit")
            raise ForbiddenError(
                "Sky support access requires an active JIT consent session"
            )

        # Customer admins bypass.
        if user.role == "admin":
            await self._audit_decision(user, permission_key, "allow", "admin_bypass", resource_id=resource_id)
            return

        eff = await self.get_effective_permissions(
            user, crew_id=crew_id, space_id=space_id, connection_id=connection_id
        )

        if not eff.permissions.get(permission_key, False):
            await self._audit_decision(user, permission_key, "deny", f"role={eff.crew_role}", resource_id=resource_id)
            raise ForbiddenError(f"Permission denied: {permission_key}")

        await self._audit_decision(user, permission_key, "allow", f"role={eff.crew_role}", resource_id=resource_id)

    async def _resolve_context_crew_role(
        self,
        user_id: UUID,
        *,
        crew_id: Optional[UUID],
        space_id: Optional[UUID],
        connection_id: Optional[UUID],
    ) -> CrewRole:
        # Most specific: crew_id
        if crew_id:
            member = await self.crew_members.get_by_crew_and_user(crew_id, user_id)
            return member.role if member and member.role else "guest"  # type: ignore[return-value]

        # Next: resolve from space_id (best role among crews in that space)
        if space_id:
            return await self._best_role_for_user_in_space(user_id, space_id)

        # Next: resolve from connection_id (any crew/space permission that user belongs to)
        if connection_id:
            return await self._best_role_for_user_for_connection(user_id, connection_id)

        # Fallback: best role across all crews
        return await self._best_role_for_user_anywhere(user_id)

    async def _best_role_for_user_in_space(self, user_id: UUID, space_id: UUID) -> CrewRole:
        crew_ids = await self.crew_members.get_crew_ids_by_user_and_space(
            user_id=user_id, space_id=space_id
        )
        if not crew_ids:
            return "guest"

        best_role = "guest"
        best_score = ROLE_PRECEDENCE[best_role]
        for cid in crew_ids:
            member = await self.crew_members.get_by_crew_and_user(cid, user_id)
            role = member.role if member and member.role else "guest"  # type: ignore[assignment]
            score = ROLE_PRECEDENCE.get(role, 0)
            if score > best_score:
                best_score = score
                best_role = role
        return best_role

    async def _best_role_for_user_anywhere(self, user_id: UUID) -> CrewRole:
        crew_ids = await self.crew_members.get_crew_ids_by_user(user_id)
        if not crew_ids:
            return "guest"

        best_role = "guest"
        best_score = ROLE_PRECEDENCE[best_role]
        for cid in crew_ids:
            member = await self.crew_members.get_by_crew_and_user(cid, user_id)
            role = member.role if member and member.role else "guest"  # type: ignore[assignment]
            score = ROLE_PRECEDENCE.get(role, 0)
            if score > best_score:
                best_score = score
                best_role = role
        return best_role

    async def _best_role_for_user_for_connection(
        self, user_id: UUID, connection_id: UUID
    ) -> CrewRole:
        # Owner can manage their connections in the interim model.
        conn = await self.connection_repo.get_by_id(connection_id)
        if conn and conn.created_by == user_id:
            return "commander"

        # Look at connection_permissions, if any, and pick best role in any linked crew/space.
        perms = await self.connection_perms.get_by_connection_id(connection_id)
        best_role = "guest"
        best_score = ROLE_PRECEDENCE[best_role]

        for p in perms:
            if p.crew_id:
                member = await self.crew_members.get_by_crew_and_user(p.crew_id, user_id)
                role = member.role if member and member.role else "guest"  # type: ignore[assignment]
                score = ROLE_PRECEDENCE.get(role, 0)
                if score > best_score:
                    best_score = score
                    best_role = role
            elif p.space_id:
                role = await self._best_role_for_user_in_space(user_id, p.space_id)
                score = ROLE_PRECEDENCE.get(role, 0)
                if score > best_score:
                    best_score = score
                    best_role = role

        return best_role
