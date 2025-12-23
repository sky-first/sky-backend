"""Planet service."""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError, NotFoundError
from src.models.user import User
from src.models.planet import Planet, PlanetMember
from src.repositories.planet import PlanetMemberRepository, PlanetRepository
from src.schemas.planet import (
    PlanetCreate,
    PlanetMemberCreate,
    PlanetMemberResponse,
    PlanetResponse,
    PlanetUpdate,
)


class PlanetService:
    """Planet service."""

    def __init__(self, db: AsyncSession):
        """
        Initialize planet service.

        Args:
            db: Database session
        """
        self.db = db
        self.planet_repo = PlanetRepository(db)
        self.member_repo = PlanetMemberRepository(db)

    async def create_planet(
        self, user: User, planet_data: PlanetCreate
    ) -> PlanetResponse:
        """
        Create a new planet.

        Args:
            user: Current user
            planet_data: Planet creation data

        Returns:
            PlanetResponse: Created planet
        """
        planet = await self.planet_repo.create(
            name=planet_data.name,
            description=planet_data.description,
            type=planet_data.type,
            color=planet_data.color,
            icon=planet_data.icon,
            owner_id=user.id,
            is_active=False,
        )

        # Add owner as member
        await self.member_repo.create(
            planet_id=planet.id,
            user_id=user.id,
            role="owner",
        )

        await self.db.commit()
        await self.db.refresh(planet)

        return PlanetResponse.model_validate(planet)

    async def get_planet(self, planet_id: UUID, user: User) -> PlanetResponse:
        """
        Get planet by ID.

        Args:
            planet_id: Planet ID
            user: Current user

        Returns:
            PlanetResponse: Planet data

        Raises:
            NotFoundError: If planet not found
            ForbiddenError: If user doesn't have access
        """
        planet = await self.planet_repo.get_by_id(planet_id)
        if not planet or planet.deleted_at:
            raise NotFoundError("Planet not found")

        # Check access
        if planet.owner_id != user.id:
            member = await self.member_repo.get_by_planet_and_user(
                planet_id, user.id
            )
            if not member:
                raise ForbiddenError("Access denied to this planet")

        return PlanetResponse.model_validate(planet)

    async def get_user_planets(self, user: User) -> List[PlanetResponse]:
        """
        Get all planets for user.

        Args:
            user: Current user

        Returns:
            List[PlanetResponse]: List of planets
        """
        planets = await self.planet_repo.get_user_planets(user.id)
        return [PlanetResponse.model_validate(w) for w in planets]

    async def update_planet(
        self, planet_id: UUID, user: User, planet_data: PlanetUpdate
    ) -> PlanetResponse:
        """
        Update planet.

        Args:
            planet_id: Planet ID
            user: Current user
            planet_data: Planet update data

        Returns:
            PlanetResponse: Updated planet

        Raises:
            NotFoundError: If planet not found
            ForbiddenError: If user doesn't have permission
        """
        planet = await self.planet_repo.get_by_id(planet_id)
        if not planet or planet.deleted_at:
            raise NotFoundError("Planet not found")

        # Check permission (only owner or admin can update)
        if planet.owner_id != user.id:
            member = await self.member_repo.get_by_planet_and_user(
                planet_id, user.id
            )
            if not member or member.role not in ["owner", "admin"]:
                raise ForbiddenError("Permission denied")

        update_data = planet_data.model_dump(exclude_unset=True)
        planet = await self.planet_repo.update(planet_id, **update_data)
        await self.db.commit()
        await self.db.refresh(planet)

        return PlanetResponse.model_validate(planet)

    async def delete_planet(self, planet_id: UUID, user: User) -> None:
        """
        Delete planet.

        Args:
            planet_id: Planet ID
            user: Current user

        Raises:
            NotFoundError: If planet not found
            ForbiddenError: If user is not owner
        """
        planet = await self.planet_repo.get_by_id(planet_id)
        if not planet or planet.deleted_at:
            raise NotFoundError("Planet not found")

        # Only owner can delete
        if planet.owner_id != user.id:
            raise ForbiddenError("Only planet owner can delete")

        await self.planet_repo.delete(planet_id)
        await self.db.commit()

    async def switch_planet(
        self, planet_id: UUID, user: User
    ) -> PlanetResponse:
        """
        Switch active planet.

        Args:
            planet_id: Planet ID to switch to
            user: Current user

        Returns:
            PlanetResponse: Active planet

        Raises:
            NotFoundError: If planet not found
            ForbiddenError: If user doesn't have access
        """
        planet = await self.planet_repo.get_by_id(planet_id)
        if not planet or planet.deleted_at:
            raise NotFoundError("Planet not found")

        # Check access
        if planet.owner_id != user.id:
            member = await self.member_repo.get_by_planet_and_user(
                planet_id, user.id
            )
            if not member:
                raise ForbiddenError("Access denied to this planet")

        # Deactivate all other planets for this user
        from sqlalchemy import update

        await self.db.execute(
            update(Planet)
            .where(Planet.owner_id == user.id, Planet.id != planet_id)
            .values(is_active=False)
        )

        # Activate this planet
        planet.is_active = True
        planet.last_accessed = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(planet)

        return PlanetResponse.model_validate(planet)

    async def add_member(
        self, planet_id: UUID, user: User, member_data: PlanetMemberCreate
    ) -> PlanetMemberResponse:
        """
        Add member to planet.

        Args:
            planet_id: Planet ID
            user: Current user
            member_data: Member data

        Returns:
            PlanetMemberResponse: Created member

        Raises:
            NotFoundError: If planet not found
            ForbiddenError: If user doesn't have permission
        """
        planet = await self.planet_repo.get_by_id(planet_id)
        if not planet or planet.deleted_at:
            raise NotFoundError("Planet not found")

        # Check permission (only owner or admin can add members)
        if planet.owner_id != user.id:
            member = await self.member_repo.get_by_planet_and_user(
                planet_id, user.id
            )
            if not member or member.role not in ["owner", "admin"]:
                raise ForbiddenError("Permission denied")

        # Check if member already exists
        existing = await self.member_repo.get_by_planet_and_user(
            planet_id, member_data.user_id
        )
        if existing:
            raise ForbiddenError("User is already a member")

        member = await self.member_repo.create(
            planet_id=planet_id,
            user_id=member_data.user_id,
            role=member_data.role,
        )
        await self.db.commit()
        await self.db.refresh(member)

        return PlanetMemberResponse.model_validate(member)

    async def remove_member(
        self, planet_id: UUID, user_id: UUID, current_user: User
    ) -> None:
        """
        Remove member from planet.

        Args:
            planet_id: Planet ID
            user_id: User ID to remove
            current_user: Current user

        Raises:
            NotFoundError: If planet or member not found
            ForbiddenError: If user doesn't have permission
        """
        planet = await self.planet_repo.get_by_id(planet_id)
        if not planet or planet.deleted_at:
            raise NotFoundError("Planet not found")

        # Check permission (only owner or admin can remove members)
        if planet.owner_id != current_user.id:
            member = await self.member_repo.get_by_planet_and_user(
                planet_id, current_user.id
            )
            if not member or member.role not in ["owner", "admin"]:
                raise ForbiddenError("Permission denied")

        member = await self.member_repo.get_by_planet_and_user(planet_id, user_id)
        if not member:
            raise NotFoundError("Member not found")

        # Can't remove owner
        if planet.owner_id == user_id:
            raise ForbiddenError("Cannot remove planet owner")

        await self.member_repo.delete(member.id)
        await self.db.commit()

    async def get_planet_members(
        self, planet_id: UUID, user: User
    ) -> List[PlanetMemberResponse]:
        """
        Get all members of a planet.

        Args:
            planet_id: Planet ID
            user: Current user

        Returns:
            List[PlanetMemberResponse]: List of planet members

        Raises:
            NotFoundError: If planet not found
            ForbiddenError: If user doesn't have access
        """
        planet = await self.planet_repo.get_by_id(planet_id)
        if not planet or planet.deleted_at:
            raise NotFoundError("Planet not found")

        # Check access (must be member or owner)
        if planet.owner_id != user.id:
            member = await self.member_repo.get_by_planet_and_user(
                planet_id, user.id
            )
            if not member:
                raise ForbiddenError("Access denied to this planet")

        members = await self.member_repo.get_planet_members(planet_id)
        return [PlanetMemberResponse.model_validate(m) for m in members]

    async def update_member_role(
        self, planet_id: UUID, user_id: UUID, new_role: str, current_user: User
    ) -> PlanetMemberResponse:
        """
        Update member role in planet.

        Args:
            planet_id: Planet ID
            user_id: User ID to update
            new_role: New role
            current_user: Current user

        Returns:
            PlanetMemberResponse: Updated member

        Raises:
            NotFoundError: If planet or member not found
            ForbiddenError: If user doesn't have permission
        """
        planet = await self.planet_repo.get_by_id(planet_id)
        if not planet or planet.deleted_at:
            raise NotFoundError("Planet not found")

        # Check permission (only owner or admin can update roles)
        if planet.owner_id != current_user.id:
            member = await self.member_repo.get_by_planet_and_user(
                planet_id, current_user.id
            )
            if not member or member.role not in ["owner", "admin"]:
                raise ForbiddenError("Permission denied")

        member = await self.member_repo.get_by_planet_and_user(planet_id, user_id)
        if not member:
            raise NotFoundError("Member not found")

        # Can't change owner role
        if planet.owner_id == user_id:
            raise ForbiddenError("Cannot change planet owner role")

        # Validate role
        if new_role not in ["admin", "member", "viewer"]:
            raise ForbiddenError("Invalid role")

        member.role = new_role
        await self.db.commit()
        await self.db.refresh(member)

        return PlanetMemberResponse.model_validate(member)

