"""Workspace service."""

from datetime import datetime, timezone
from typing import List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError, NotFoundError
from src.models.user import User
from src.models.workspace import Workspace
from src.repositories.workspace import WorkspaceMemberRepository, WorkspaceRepository
from src.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceMemberCreate,
    WorkspaceMemberResponse,
    WorkspaceResponse,
    WorkspaceUpdate,
)


class WorkspaceService:
    """Workspace service."""

    def __init__(self, db: AsyncSession):
        """
        Initialize workspace service.

        Args:
            db: Database session
        """
        self.db = db
        self.workspace_repo = WorkspaceRepository(db)
        self.member_repo = WorkspaceMemberRepository(db)

    async def create_workspace(
        self, user: User, workspace_data: WorkspaceCreate
    ) -> WorkspaceResponse:
        """
        Create a new workspace.

        Args:
            user: Current user
            workspace_data: Workspace creation data

        Returns:
            WorkspaceResponse: Created workspace
        """
        workspace = await self.workspace_repo.create(
            name=workspace_data.name,
            description=workspace_data.description,
            type=workspace_data.type,
            color=workspace_data.color,
            icon=workspace_data.icon,
            owner_id=user.id,
            is_active=False,
        )

        # Add owner as member
        await self.member_repo.create(
            workspace_id=workspace.id,
            user_id=user.id,
            role="owner",
        )

        await self.db.commit()
        await self.db.refresh(workspace)

        return WorkspaceResponse.model_validate(workspace)

    async def get_workspace(self, workspace_id: UUID, user: User) -> WorkspaceResponse:
        """
        Get workspace by ID.

        Args:
            workspace_id: Workspace ID
            user: Current user

        Returns:
            WorkspaceResponse: Workspace data

        Raises:
            NotFoundError: If workspace not found
            ForbiddenError: If user doesn't have access
        """
        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if not workspace or workspace.deleted_at:
            raise NotFoundError("Workspace not found")

        # Check access
        if workspace.owner_id != user.id:
            member = await self.member_repo.get_by_workspace_and_user(workspace_id, user.id)
            if not member:
                raise ForbiddenError("Access denied to this workspace")

        return WorkspaceResponse.model_validate(workspace)

    async def get_user_workspaces(self, user: User) -> List[WorkspaceResponse]:
        """
        Get all workspaces for user.

        Args:
            user: Current user

        Returns:
            List[WorkspaceResponse]: List of workspaces
        """
        workspaces = await self.workspace_repo.get_user_workspaces(user.id)
        return [WorkspaceResponse.model_validate(w) for w in workspaces]

    async def update_workspace(
        self, workspace_id: UUID, user: User, workspace_data: WorkspaceUpdate
    ) -> WorkspaceResponse:
        """
        Update workspace.

        Args:
            workspace_id: Workspace ID
            user: Current user
            workspace_data: Workspace update data

        Returns:
            WorkspaceResponse: Updated workspace

        Raises:
            NotFoundError: If workspace not found
            ForbiddenError: If user doesn't have permission
        """
        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if not workspace or workspace.deleted_at:
            raise NotFoundError("Workspace not found")

        # Check permission (only owner or admin can update)
        if workspace.owner_id != user.id:
            member = await self.member_repo.get_by_workspace_and_user(workspace_id, user.id)
            if not member or member.role not in ["owner", "admin"]:
                raise ForbiddenError("Permission denied")

        update_data = workspace_data.model_dump(exclude_unset=True)
        workspace = await self.workspace_repo.update(workspace_id, **update_data)
        await self.db.commit()
        await self.db.refresh(workspace)

        return WorkspaceResponse.model_validate(workspace)

    async def delete_workspace(self, workspace_id: UUID, user: User) -> None:
        """
        Delete workspace.

        Args:
            workspace_id: Workspace ID
            user: Current user

        Raises:
            NotFoundError: If workspace not found
            ForbiddenError: If user is not owner
        """
        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if not workspace or workspace.deleted_at:
            raise NotFoundError("Workspace not found")

        # Only owner can delete
        if workspace.owner_id != user.id:
            raise ForbiddenError("Only workspace owner can delete")

        await self.workspace_repo.delete(workspace_id)
        await self.db.commit()

    async def switch_workspace(self, workspace_id: UUID, user: User) -> WorkspaceResponse:
        """
        Switch active workspace.

        Args:
            workspace_id: Workspace ID to switch to
            user: Current user

        Returns:
            WorkspaceResponse: Active workspace

        Raises:
            NotFoundError: If workspace not found
            ForbiddenError: If user doesn't have access
        """
        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if not workspace or workspace.deleted_at:
            raise NotFoundError("Workspace not found")

        # Check access
        if workspace.owner_id != user.id:
            member = await self.member_repo.get_by_workspace_and_user(workspace_id, user.id)
            if not member:
                raise ForbiddenError("Access denied to this workspace")

        # Deactivate all other workspaces for this user
        from sqlalchemy import update

        await self.db.execute(
            update(Workspace)
            .where(Workspace.owner_id == user.id, Workspace.id != workspace_id)
            .values(is_active=False)
        )

        # Activate this workspace
        workspace.is_active = True
        workspace.last_accessed = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(workspace)

        return WorkspaceResponse.model_validate(workspace)

    async def add_member(
        self, workspace_id: UUID, user: User, member_data: WorkspaceMemberCreate
    ) -> WorkspaceMemberResponse:
        """
        Add member to workspace.

        Args:
            workspace_id: Workspace ID
            user: Current user
            member_data: Member data

        Returns:
            WorkspaceMemberResponse: Created member

        Raises:
            NotFoundError: If workspace not found
            ForbiddenError: If user doesn't have permission
        """
        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if not workspace or workspace.deleted_at:
            raise NotFoundError("Workspace not found")

        # Check permission (only owner or admin can add members)
        if workspace.owner_id != user.id:
            member = await self.member_repo.get_by_workspace_and_user(workspace_id, user.id)
            if not member or member.role not in ["owner", "admin"]:
                raise ForbiddenError("Permission denied")

        # Check if member already exists
        existing = await self.member_repo.get_by_workspace_and_user(
            workspace_id, member_data.user_id
        )
        if existing:
            raise ForbiddenError("User is already a member")

        member = await self.member_repo.create(
            workspace_id=workspace_id,
            user_id=member_data.user_id,
            role=member_data.role,
        )
        await self.db.commit()
        await self.db.refresh(member)

        return WorkspaceMemberResponse.model_validate(member)

    async def remove_member(self, workspace_id: UUID, user_id: UUID, current_user: User) -> None:
        """
        Remove member from workspace.

        Args:
            workspace_id: Workspace ID
            user_id: User ID to remove
            current_user: Current user

        Raises:
            NotFoundError: If workspace or member not found
            ForbiddenError: If user doesn't have permission
        """
        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if not workspace or workspace.deleted_at:
            raise NotFoundError("Workspace not found")

        # Check permission (only owner or admin can remove members)
        if workspace.owner_id != current_user.id:
            member = await self.member_repo.get_by_workspace_and_user(workspace_id, current_user.id)
            if not member or member.role not in ["owner", "admin"]:
                raise ForbiddenError("Permission denied")

        member = await self.member_repo.get_by_workspace_and_user(workspace_id, user_id)
        if not member:
            raise NotFoundError("Member not found")

        # Can't remove owner
        if workspace.owner_id == user_id:
            raise ForbiddenError("Cannot remove workspace owner")

        await self.member_repo.delete(member.id)
        await self.db.commit()

    async def get_workspace_members(
        self, workspace_id: UUID, user: User
    ) -> List[WorkspaceMemberResponse]:
        """
        Get all members of a workspace.

        Args:
            workspace_id: Workspace ID
            user: Current user

        Returns:
            List[WorkspaceMemberResponse]: List of workspace members

        Raises:
            NotFoundError: If workspace not found
            ForbiddenError: If user doesn't have access
        """
        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if not workspace or workspace.deleted_at:
            raise NotFoundError("Workspace not found")

        # Check access (must be member or owner)
        if workspace.owner_id != user.id:
            member = await self.member_repo.get_by_workspace_and_user(workspace_id, user.id)
            if not member:
                raise ForbiddenError("Access denied to this workspace")

        members = await self.member_repo.get_workspace_members(workspace_id)
        return [WorkspaceMemberResponse.model_validate(m) for m in members]

    async def update_member_role(
        self, workspace_id: UUID, user_id: UUID, new_role: str, current_user: User
    ) -> WorkspaceMemberResponse:
        """
        Update member role in workspace.

        Args:
            workspace_id: Workspace ID
            user_id: User ID to update
            new_role: New role
            current_user: Current user

        Returns:
            WorkspaceMemberResponse: Updated member

        Raises:
            NotFoundError: If workspace or member not found
            ForbiddenError: If user doesn't have permission
        """
        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if not workspace or workspace.deleted_at:
            raise NotFoundError("Workspace not found")

        # Check permission (only owner or admin can update roles)
        if workspace.owner_id != current_user.id:
            member = await self.member_repo.get_by_workspace_and_user(workspace_id, current_user.id)
            if not member or member.role not in ["owner", "admin"]:
                raise ForbiddenError("Permission denied")

        member = await self.member_repo.get_by_workspace_and_user(workspace_id, user_id)
        if not member:
            raise NotFoundError("Member not found")

        # Can't change owner role
        if workspace.owner_id == user_id:
            raise ForbiddenError("Cannot change workspace owner role")

        # Validate role
        if new_role not in ["admin", "member", "viewer"]:
            raise ForbiddenError("Invalid role")

        member.role = new_role
        await self.db.commit()
        await self.db.refresh(member)

        return WorkspaceMemberResponse.model_validate(member)
