"""Workspace repository."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.workspace import Workspace, WorkspaceMember
from src.repositories.base import BaseRepository


class WorkspaceRepository(BaseRepository[Workspace]):
    """Workspace repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Workspace)

    async def get_by_owner(
        self, owner_id: UUID, skip: int = 0, limit: int = 100
    ) -> List[Workspace]:
        """
        Get workspaces by owner.

        Args:
            owner_id: Owner user ID
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List[Workspace]: List of workspaces
        """
        result = await self.db.execute(
            select(Workspace)
            .where(Workspace.owner_id == owner_id, Workspace.deleted_at.is_(None))
            .order_by(Workspace.last_accessed.desc().nulls_last(), Workspace.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_active_workspace(self, user_id: UUID) -> Optional[Workspace]:
        """
        Get active workspace for user.

        Args:
            user_id: User ID

        Returns:
            Optional[Workspace]: Active workspace or None
        """
        # First try to find workspace where user is owner and is_active = True
        result = await self.db.execute(
            select(Workspace)
            .where(
                Workspace.owner_id == user_id,
                Workspace.is_active == True,  # noqa: E712
                Workspace.deleted_at.is_(None),
            )
            .options(selectinload(Workspace.members), selectinload(Workspace.dashboards))
        )
        workspace = result.scalar_one_or_none()

        if workspace:
            return workspace

        # If no active workspace, get the most recently accessed
        result = await self.db.execute(
            select(Workspace)
            .where(Workspace.owner_id == user_id, Workspace.deleted_at.is_(None))
            .order_by(Workspace.last_accessed.desc().nulls_last(), Workspace.created_at.desc())
            .limit(1)
            .options(selectinload(Workspace.members), selectinload(Workspace.dashboards))
        )
        return result.scalar_one_or_none()

    async def get_user_workspaces(self, user_id: UUID) -> List[Workspace]:
        """
        Get all workspaces user has access to (as owner or member).

        Args:
            user_id: User ID

        Returns:
            List[Workspace]: List of workspaces
        """
        # Workspaces where user is owner
        owned_result = await self.db.execute(
            select(Workspace).where(
                Workspace.owner_id == user_id, Workspace.deleted_at.is_(None)
            )
        )
        owned = list(owned_result.scalars().all())

        # Workspaces where user is member
        member_result = await self.db.execute(
            select(Workspace)
            .join(WorkspaceMember)
            .where(
                WorkspaceMember.user_id == user_id,
                Workspace.deleted_at.is_(None),
            )
        )
        member_workspaces = list(member_result.scalars().all())

        # Combine and deduplicate
        all_workspaces = {w.id: w for w in owned + member_workspaces}
        return list(all_workspaces.values())


class WorkspaceMemberRepository(BaseRepository[WorkspaceMember]):
    """Workspace member repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, WorkspaceMember)

    async def get_by_workspace_and_user(
        self, workspace_id: UUID, user_id: UUID
    ) -> Optional[WorkspaceMember]:
        """
        Get workspace member by workspace and user.

        Args:
            workspace_id: Workspace ID
            user_id: User ID

        Returns:
            Optional[WorkspaceMember]: Member or None
        """
        result = await self.db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_workspace_members(
        self, workspace_id: UUID
    ) -> List[WorkspaceMember]:
        """
        Get all members of a workspace.

        Args:
            workspace_id: Workspace ID

        Returns:
            List[WorkspaceMember]: List of members
        """
        result = await self.db.execute(
            select(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .options(selectinload(WorkspaceMember.user))
        )
        return list(result.scalars().all())

