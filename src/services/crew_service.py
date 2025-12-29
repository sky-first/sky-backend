"""Crew service."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.models.user import User
from src.repositories.crew import CrewMemberRepository, CrewRepository
from src.repositories.space import SpaceRepository
from src.schemas.crew import (
    CrewCreate,
    CrewMemberCreate,
    CrewMemberResponse,
    CrewMemberUpdate,
    CrewResponse,
    CrewUpdate,
)
from src.services.auth_service import user_to_response_dict


class CrewService:
    """Crew service."""

    def __init__(self, db: AsyncSession):
        """
        Initialize crew service.

        Args:
            db: Database session
        """
        self.db = db
        self.crew_repo = CrewRepository(db)
        self.member_repo = CrewMemberRepository(db)
        self.space_repo = SpaceRepository(db)

    async def list_crews(
        self, user: User, space_id: Optional[UUID] = None, skip: int = 0, limit: int = 100
    ) -> List[CrewResponse]:
        """
        List crews.

        Args:
            user: Current user
            space_id: Optional space ID to filter
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List[CrewResponse]: List of crews
        """
        if space_id:
            crews = await self.crew_repo.get_by_space(space_id, skip=skip, limit=limit)
        else:
            # Get all crews user has access to
            crews = await self.crew_repo.get_all(skip=skip, limit=limit)

        return [CrewResponse.model_validate(c) for c in crews]

    async def get_crew(self, crew_id: UUID, user: User) -> CrewResponse:
        """
        Get crew by ID.

        Args:
            crew_id: Crew ID
            user: Current user

        Returns:
            CrewResponse: Crew data

        Raises:
            NotFoundError: If crew not found
            ForbiddenError: If user doesn't have access
        """
        crew = await self.crew_repo.get_by_id(crew_id)
        if not crew:
            raise NotFoundError("Crew not found")

        # Check access via space
        space = await self.space_repo.get_by_id(crew.space_id)
        if not space or space.created_by != user.id:
            raise ForbiddenError("Access denied to this crew")

        return CrewResponse.model_validate(crew)

    async def create_crew(self, user: User, crew_data: CrewCreate) -> CrewResponse:
        """
        Create a new crew.

        Args:
            user: Current user
            crew_data: Crew creation data

        Returns:
            CrewResponse: Created crew

        Raises:
            NotFoundError: If space not found
            ForbiddenError: If user doesn't have access to space
        """
        # Verify space exists and user has access
        space = await self.space_repo.get_by_id(crew_data.space_id)
        if not space:
            raise NotFoundError("Space not found")

        if space.created_by != user.id:
            raise ForbiddenError("Access denied to this space")

        crew = await self.crew_repo.create(
            name=crew_data.name,
            description=crew_data.description,
            space_id=crew_data.space_id,
            created_by=user.id,
        )

        await self.db.commit()
        await self.db.refresh(crew)

        return CrewResponse.model_validate(crew)

    async def update_crew(
        self, crew_id: UUID, user: User, crew_data: CrewUpdate
    ) -> CrewResponse:
        """
        Update crew.

        Args:
            crew_id: Crew ID
            user: Current user
            crew_data: Crew update data

        Returns:
            CrewResponse: Updated crew

        Raises:
            NotFoundError: If crew not found
            ForbiddenError: If user doesn't have access
        """
        crew = await self.crew_repo.get_by_id(crew_id)
        if not crew:
            raise NotFoundError("Crew not found")

        # Check access via current space
        current_space = await self.space_repo.get_by_id(crew.space_id)
        if not current_space or current_space.created_by != user.id:
            raise ForbiddenError("Access denied to this crew")

        update_data = crew_data.model_dump(exclude_unset=True)

        # If moving crew to another space, validate target space ownership
        if "space_id" in update_data and update_data["space_id"] != crew.space_id:
            target_space = await self.space_repo.get_by_id(update_data["space_id"])
            if not target_space:
                raise NotFoundError("Target space not found")
            if target_space.created_by != user.id:
                raise ForbiddenError("Access denied to target space")

        crew = await self.crew_repo.update(crew_id, **update_data)
        await self.db.commit()
        await self.db.refresh(crew)

        return CrewResponse.model_validate(crew)

    async def delete_crew(self, crew_id: UUID, user: User) -> None:
        """
        Delete crew.

        Args:
            crew_id: Crew ID
            user: Current user

        Raises:
            NotFoundError: If crew not found
            ForbiddenError: If user doesn't have access
        """
        from src.config.settings import get_settings
        import logging

        logger = logging.getLogger(__name__)

        # Use get_by_id_including_deleted to find crew even if it's already soft-deleted
        # This allows us to handle cases where the crew might have been deleted but we still need to verify
        crew = await self.crew_repo.get_by_id_including_deleted(crew_id)
        if not crew:
            logger.error(f"🔴 [DELETE SERVICE] Crew {crew_id} not found in database")
            raise NotFoundError("Crew not found")

        # Check if crew is already deleted
        if crew.deleted_at is not None:
            logger.warning(f"🔴 [DELETE SERVICE] Crew {crew_id} is already deleted (deleted_at: {crew.deleted_at})")
            # Don't raise error, just return - crew is already deleted
            return

        settings = get_settings()
        
        # In development, allow any user to delete any crew
        # In production, only admin or owner can delete
        if settings.is_development:
            # Development mode: allow any authenticated user to delete
            logger.info(f"🔴 [DELETE SERVICE] Development mode: Allowing user {user.id} to delete crew {crew_id} (space created by {crew.space_id})")
        else:
            # Production mode: only admin or owner can delete
            space = await self.space_repo.get_by_id(crew.space_id)
            if not space or space.created_by != user.id:
                raise ForbiddenError("Access denied to this crew")

        logger.info(f"🔴 [DELETE SERVICE] Calling crew_repo.delete for crew {crew_id}")
        await self.crew_repo.delete(crew_id)
        await self.db.commit()
        logger.info(f"🔴 [DELETE SERVICE] Crew {crew_id} soft-deleted successfully (deleted_at set)")

    async def get_crew_members(
        self, crew_id: UUID, user: User
    ) -> List[CrewMemberResponse]:
        """
        Get members for a crew.

        Args:
            crew_id: Crew ID
            user: Current user

        Returns:
            List[CrewMemberResponse]: List of crew members

        Raises:
            NotFoundError: If crew not found
            ForbiddenError: If user doesn't have access
        """
        crew = await self.crew_repo.get_by_id(crew_id)
        if not crew:
            raise NotFoundError("Crew not found")

        # Check access via space
        space = await self.space_repo.get_by_id(crew.space_id)
        if not space or space.created_by != user.id:
            raise ForbiddenError("Access denied to this crew")

        members = await self.member_repo.get_by_crew(crew_id)
        # Refresh user relationships to ensure they're loaded
        for member in members:
            await self.db.refresh(member, ["user"])
        
        # Convert to response format with user info
        result = []
        for member in members:
            member_data_dict = {
                "id": member.id,
                "crew_id": member.crew_id,
                "user_id": member.user_id,
                "role": member.role,
                "joined_at": member.joined_at,
                "created_at": member.created_at,
                "user": user_to_response_dict(member.user) if member.user else None,
            }
            result.append(CrewMemberResponse.model_validate(member_data_dict))
        
        return result

    async def add_crew_member(
        self, crew_id: UUID, user: User, member_data: CrewMemberCreate
    ) -> CrewMemberResponse:
        """
        Add member to crew.

        Args:
            crew_id: Crew ID
            user: Current user
            member_data: Member data

        Returns:
            CrewMemberResponse: Created member

        Raises:
            NotFoundError: If crew not found
            ForbiddenError: If user doesn't have access
            BadRequestError: If member already exists
        """
        crew = await self.crew_repo.get_by_id(crew_id)
        if not crew:
            raise NotFoundError("Crew not found")

        # Check access via space
        space = await self.space_repo.get_by_id(crew.space_id)
        if not space or space.created_by != user.id:
            raise ForbiddenError("Access denied to this crew")

        # Check if member already exists
        existing = await self.member_repo.get_by_crew_and_user(crew_id, member_data.user_id)
        if existing:
            raise BadRequestError("User is already a member of this crew")

        member = await self.member_repo.create(
            crew_id=crew_id,
            user_id=member_data.user_id,
            role=member_data.role,
        )

        await self.db.commit()
        # Load user relationship (similar to SpaceService)
        await self.db.refresh(member, ["user"])
        
        # Convert user to dict if present (CrewMemberResponse expects Optional[dict])
        from src.schemas.user import UserResponse
        member_data_dict = {
            "id": member.id,
            "crew_id": member.crew_id,
            "user_id": member.user_id,
            "role": member.role,
            "joined_at": member.joined_at,
            "created_at": member.created_at,
            "user": user_to_response_dict(member.user) if member.user else None,
        }
        return CrewMemberResponse.model_validate(member_data_dict)

    async def remove_crew_member(
        self, crew_id: UUID, user_id: UUID, current_user: User
    ) -> None:
        """
        Remove member from crew.

        Args:
            crew_id: Crew ID
            user_id: User ID to remove
            current_user: Current user

        Raises:
            NotFoundError: If crew or member not found
            ForbiddenError: If user doesn't have access
        """
        crew = await self.crew_repo.get_by_id(crew_id)
        if not crew:
            raise NotFoundError("Crew not found")

        # Check access via space
        space = await self.space_repo.get_by_id(crew.space_id)
        if not space or space.created_by != current_user.id:
            raise ForbiddenError("Access denied to this crew")

        member = await self.member_repo.get_by_crew_and_user(crew_id, user_id)
        if not member:
            raise NotFoundError("Member not found")

        await self.member_repo.delete(member.id)
        await self.db.commit()

    async def update_crew_member_role(
        self, crew_id: UUID, user_id: UUID, role_data: CrewMemberUpdate, current_user: User
    ) -> CrewMemberResponse:
        """
        Update crew member role.

        Args:
            crew_id: Crew ID
            user_id: User ID of the member
            role_data: New role
            current_user: Current user

        Returns:
            CrewMemberResponse: Updated member

        Raises:
            NotFoundError: If crew or member not found
            ForbiddenError: If user doesn't have access
        """
        crew = await self.crew_repo.get_by_id(crew_id)
        if not crew:
            raise NotFoundError("Crew not found")

        # Check access via space
        space = await self.space_repo.get_by_id(crew.space_id)
        if not space or space.created_by != current_user.id:
            raise ForbiddenError("Access denied to this crew")

        member = await self.member_repo.get_by_crew_and_user(crew_id, user_id)
        if not member:
            raise NotFoundError("Member not found")

        member = await self.member_repo.update(member.id, role=role_data.role)
        await self.db.commit()
        
        # Reload member with user relationship
        await self.db.refresh(member, ["user"])
        
        # Build response dict similar to get_crew_members
        member_data_dict = {
            "id": member.id,
            "crew_id": member.crew_id,
            "user_id": member.user_id,
            "role": member.role,
            "joined_at": member.joined_at,
            "created_at": member.created_at,
            "user": user_to_response_dict(member.user) if member.user else None,
        }
        
        return CrewMemberResponse.model_validate(member_data_dict)

