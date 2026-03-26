"""Onboarding helpers to ensure default planet/space for new users."""

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User
from src.repositories.planet import PlanetMemberRepository, PlanetRepository
from src.repositories.space import SpaceRepository


async def ensure_default_planet_and_space(db: AsyncSession, user: User) -> None:
    """
    Ensure a user has at least one planet and a default space.

    Idempotent: if the user already owns a planet, it does nothing.
    """
    planet_repo = PlanetRepository(db)
    space_repo = SpaceRepository(db)
    planet_member_repo = PlanetMemberRepository(db)

    # Already has planet? Do nothing.
    existing_planets = await planet_repo.get_by_owner(user.id, limit=1)
    if existing_planets:
        return

    # Create a default planet
    planet_name = f"{user.name.split(' ')[0]}'s planet" if user.name else "My first planet"
    planet = await planet_repo.create(
        name=planet_name,
        description="Your first planet",
        type="personal",
        color="#3B82F6",  # default blue
        icon=None,
        owner_id=user.id,
        is_active=True,
    )

    # Add the user as owner/member
    await planet_member_repo.create(
        planet_id=planet.id,
        user_id=user.id,
        role="owner",
    )

    # Create a default space
    await space_repo.create(
        name="Default space",
        description="Your first space",
        color="#3B82F6",
        icon=None,
        created_by=user.id,
    )

    # Create a default dashboard for the new planet
    from src.repositories.dashboard import DashboardRepository

    dashboard_repo = DashboardRepository(db)
    await dashboard_repo.create(
        name="My Dashboard",
        description="Your first dashboard",
        planet_id=planet.id,
        created_by=user.id,
        canvas_settings={
            "scale": 1,
            "position": {"x": 0, "y": 0},
            "snapToGrid": False,
            "gridSize": 24,
        },
        is_locked=False,
    )

    await db.commit()
    await db.refresh(planet)
