"""Space service."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.models.crew import Crew
from src.models.space import Space, SpaceConnection, SpaceMember
from src.models.user import User
from src.repositories.connection import ConnectionRepository
from src.repositories.space import SpaceMemberRepository, SpaceRepository
from src.schemas.space import (
    SpaceCreate,
    SpaceMemberCreate,
    SpaceMemberResponse,
    SpaceResponse,
    SpaceUpdate,
)


class SpaceService:
    """Space service."""

    def __init__(self, db: AsyncSession):
        """
        Initialize space service.

        Args:
            db: Database session
        """
        self.db = db
        self.space_repo = SpaceRepository(db)
        self.connection_repo = ConnectionRepository(db)
        self.member_repo = SpaceMemberRepository(db)

    async def list_spaces(
        self, user: User, skip: int = 0, limit: int = 100
    ) -> List[SpaceResponse]:
        """
        List spaces.

        Args:
            user: Current user
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List[SpaceResponse]: List of spaces
        """
        spaces = await self.space_repo.get_by_user(user.id, skip=skip, limit=limit)
        return [SpaceResponse.model_validate(s) for s in spaces]

    async def get_space(self, space_id: UUID, user: User) -> SpaceResponse:
        """
        Get space by ID.

        Args:
            space_id: Space ID
            user: Current user

        Returns:
            SpaceResponse: Space data

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        # Check access (only owner for now)
        if space.created_by != user.id:
            raise ForbiddenError("Access denied to this space")

        return SpaceResponse.model_validate(space)

    async def create_space(self, user: User, space_data: SpaceCreate) -> SpaceResponse:
        """
        Create a new space.

        Args:
            user: Current user
            space_data: Space creation data

        Returns:
            SpaceResponse: Created space
        """
        space = await self.space_repo.create(
            name=space_data.name,
            description=space_data.description,
            color=space_data.color,
            icon=space_data.icon,
            created_by=user.id,
        )

        await self.db.commit()
        await self.db.refresh(space)

        return SpaceResponse.model_validate(space)

    async def update_space(
        self, space_id: UUID, user: User, space_data: SpaceUpdate
    ) -> SpaceResponse:
        """
        Update space.

        Args:
            space_id: Space ID
            user: Current user
            space_data: Space update data

        Returns:
            SpaceResponse: Updated space

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id:
            raise ForbiddenError("Access denied to this space")

        update_data = space_data.model_dump(exclude_unset=True)
        space = await self.space_repo.update(space_id, **update_data)
        await self.db.commit()
        await self.db.refresh(space)

        return SpaceResponse.model_validate(space)

    async def delete_space(self, space_id: UUID, user: User) -> None:
        """
        Delete space.

        Args:
            space_id: Space ID
            user: Current user

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id:
            raise ForbiddenError("Access denied to this space")

        await self.space_repo.delete(space_id)
        await self.db.commit()

    async def get_space_crews(self, space_id: UUID, user: User) -> List[Crew]:
        """
        Get crews for a space.

        Args:
            space_id: Space ID
            user: Current user

        Returns:
            List[Crew]: List of crews

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id:
            raise ForbiddenError("Access denied to this space")

        crews = await self.space_repo.get_space_crews(space_id)
        return crews

    async def get_space_connections(
        self, space_id: UUID, user: User
    ) -> List[SpaceConnection]:
        """
        Get connections for a space.

        Args:
            space_id: Space ID
            user: Current user

        Returns:
            List[SpaceConnection]: List of space connections

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id:
            raise ForbiddenError("Access denied to this space")

        connections = await self.space_repo.get_space_connections(space_id)
        return connections

    async def get_space_members(
        self, space_id: UUID, user: User
    ) -> List[SpaceMemberResponse]:
        """
        Get all members of a space.

        Args:
            space_id: Space ID
            user: Current user

        Returns:
            List[SpaceMemberResponse]: List of members

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id:
            raise ForbiddenError("Access denied to this space")

        members = await self.member_repo.get_space_members(space_id)
        # Refresh user objects to ensure they're loaded
        for member in members:
            await self.db.refresh(member, ["user"])
        return [SpaceMemberResponse.model_validate(m) for m in members]

    async def add_space_member(
        self, space_id: UUID, user: User, member_data: SpaceMemberCreate
    ) -> SpaceMemberResponse:
        """
        Add member to space.

        Args:
            space_id: Space ID
            user: Current user
            member_data: Member data

        Returns:
            SpaceMemberResponse: Created member

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access
            BadRequestError: If member already exists
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id:
            raise ForbiddenError("Access denied to this space")

        # Check if member already exists
        existing = await self.member_repo.get_by_space_and_user(space_id, member_data.user_id)
        if existing:
            raise BadRequestError("User is already a member of this space")

        # Create new member
        member = await self.member_repo.create(
            space_id=space_id,
            user_id=member_data.user_id,
        )

        await self.db.commit()
        await self.db.refresh(member, ["user"])

        return SpaceMemberResponse.model_validate(member)

    async def remove_space_member(
        self, space_id: UUID, user_id: UUID, current_user: User
    ) -> None:
        """
        Remove member from space.

        Args:
            space_id: Space ID
            user_id: User ID to remove
            current_user: Current user

        Raises:
            NotFoundError: If space or member not found
            ForbiddenError: If user doesn't have access
        """
        space = await self.space_repo.get_by_id(space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != current_user.id:
            raise ForbiddenError("Access denied to this space")

        # Check if member exists
        member = await self.member_repo.get_by_space_and_user(space_id, user_id)
        if not member:
            raise NotFoundError("Member not found")

        # Don't allow removing the space creator
        if space.created_by == user_id:
            raise ForbiddenError("Cannot remove space creator")

        await self.member_repo.delete(member.id)
        await self.db.commit()

