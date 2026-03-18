"""RBAC service (effective permissions + enforcement).

This is the backend "source of truth" for RBAC. Frontend gating (Subtask 3) is
best-effort UX; this service makes the rules actually enforceable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError
from src.models.user import User
from src.repositories.connection import ConnectionRepository
from src.repositories.crew import CrewMemberRepository
from src.repositories.permission import PermissionRepository, RolePermissionRepository

CrewRole = str  # commander | navigator | explorer | guest

ROLE_PRECEDENCE: Dict[str, int] = {
    "guest": 0,
    "explorer": 1,
    "navigator": 2,
    "commander": 3,
}


DEFAULT_ROLE_PERMISSIONS: Dict[str, Dict[str, bool]] = {
    "commander": {
        "createPlanets": True,
        "viewPlanets": True,
        "editPlanets": True,
        "deletePlanets": True,
        "sharePlanets": True,
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
        "createPlanets": True,
        "viewPlanets": True,
        "editPlanets": True,
        "deletePlanets": False,
        "sharePlanets": True,
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
        "createPlanets": False,
        "viewPlanets": True,
        "editPlanets": False,
        "deletePlanets": False,
        "sharePlanets": False,
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
        "createPlanets": False,
        "viewPlanets": True,
        "editPlanets": False,
        "deletePlanets": False,
        "sharePlanets": False,
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
        # Platform admins can do everything.
        if user.role == "admin":
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

    async def assert_permission(
        self,
        user: User,
        permission_key: str,
        *,
        crew_id: Optional[UUID] = None,
        space_id: Optional[UUID] = None,
        connection_id: Optional[UUID] = None,
    ) -> None:
        # Platform admins bypass.
        if user.role == "admin":
            return

        eff = await self.get_effective_permissions(
            user, crew_id=crew_id, space_id=space_id, connection_id=connection_id
        )

        if not eff.permissions.get(permission_key, False):
            raise ForbiddenError(f"Permission denied: {permission_key}")

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
