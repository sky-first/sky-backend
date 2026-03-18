"""Planet repository."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.planet import Planet, PlanetMember
from src.repositories.base import BaseRepository


class PlanetRepository(BaseRepository[Planet]):
    """Planet repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Planet)

    async def get_by_owner(self, owner_id: UUID, skip: int = 0, limit: int = 100) -> List[Planet]:
        """
        Get planets by owner.

        Args:
            owner_id: Owner user ID
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List[Planet]: List of planets
        """
        result = await self.db.execute(
            select(Planet)
            .where(Planet.owner_id == owner_id, Planet.deleted_at.is_(None))
            .order_by(Planet.last_accessed.desc().nulls_last(), Planet.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_active_planet(self, user_id: UUID) -> Optional[Planet]:
        """
        Get active planet for user.

        Args:
            user_id: User ID

        Returns:
            Optional[Planet]: Active planet or None
        """
        # First try to find planet where user is owner and is_active = True
        result = await self.db.execute(
            select(Planet)
            .where(
                Planet.owner_id == user_id,
                Planet.is_active == True,  # noqa: E712
                Planet.deleted_at.is_(None),
            )
            .options(selectinload(Planet.members), selectinload(Planet.dashboards))
        )
        planet = result.scalar_one_or_none()

        if planet:
            return planet

        # If no active planet, get the most recently accessed
        result = await self.db.execute(
            select(Planet)
            .where(Planet.owner_id == user_id, Planet.deleted_at.is_(None))
            .order_by(Planet.last_accessed.desc().nulls_last(), Planet.created_at.desc())
            .limit(1)
            .options(selectinload(Planet.members), selectinload(Planet.dashboards))
        )
        return result.scalar_one_or_none()

    async def get_user_planets(self, user_id: UUID) -> List[Planet]:
        """
        Get all planets user has access to (as owner or member).

        Args:
            user_id: User ID

        Returns:
            List[Planet]: List of planets
        """
        # Planets where user is owner
        owned_result = await self.db.execute(
            select(Planet).where(Planet.owner_id == user_id, Planet.deleted_at.is_(None))
        )
        owned = list(owned_result.scalars().all())

        # Planets where user is member
        member_result = await self.db.execute(
            select(Planet)
            .join(PlanetMember)
            .where(
                PlanetMember.user_id == user_id,
                Planet.deleted_at.is_(None),
            )
        )
        member_planets = list(member_result.scalars().all())

        # Combine and deduplicate
        all_planets = {p.id: p for p in owned + member_planets}
        return list(all_planets.values())


class PlanetMemberRepository(BaseRepository[PlanetMember]):
    """Planet member repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, PlanetMember)

    async def get_by_planet_and_user(
        self, planet_id: UUID, user_id: UUID
    ) -> Optional[PlanetMember]:
        """
        Get planet member by planet and user.

        Args:
            planet_id: Planet ID
            user_id: User ID

        Returns:
            Optional[PlanetMember]: Member or None
        """
        result = await self.db.execute(
            select(PlanetMember).where(
                PlanetMember.planet_id == planet_id,
                PlanetMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_planet_members(self, planet_id: UUID) -> List[PlanetMember]:
        """
        Get all members of a planet.

        Args:
            planet_id: Planet ID

        Returns:
            List[PlanetMember]: List of members
        """
        result = await self.db.execute(
            select(PlanetMember)
            .where(PlanetMember.planet_id == planet_id)
            .options(selectinload(PlanetMember.user))
        )
        return list(result.scalars().all())
