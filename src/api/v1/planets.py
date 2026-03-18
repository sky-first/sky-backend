"""Planet endpoints."""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.dashboard import DashboardResponse
from src.schemas.planet import (
    PlanetCreate,
    PlanetMemberCreate,
    PlanetMemberResponse,
    PlanetMemberRoleUpdate,
    PlanetResponse,
    PlanetUpdate,
)
from src.services.dashboard_service import DashboardService
from src.services.planet_service import PlanetService
from src.services.starred_service import StarredItemService

router = APIRouter()


@router.get(
    "",
    response_model=List[PlanetResponse],
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="List planets",
    description="Get list of planets for the current user",
)
async def list_planets(
    type: Optional[str] = Query(None, pattern="^(personal|team)$"),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[PlanetResponse]:
    """
    List all planets for the current user.

    Args:
        type: Filter by planet type (personal|team)
        search: Search term for planet name
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[PlanetResponse]: List of planets
    """
    planet_service = PlanetService(db)
    planets = await planet_service.get_user_planets(current_user)

    # Apply filters
    if type:
        planets = [w for w in planets if w.type == type]
    if search:
        search_lower = search.lower()
        planets = [w for w in planets if search_lower in w.name.lower()]

    return planets


@router.get(
    "/{planet_id}",
    response_model=PlanetResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get planet",
    description="Get planet by ID",
)
async def get_planet(
    planet_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PlanetResponse:
    """
    Get planet by ID.

    Args:
        planet_id: Planet ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        PlanetResponse: Planet data
    """
    planet_service = PlanetService(db)
    return await planet_service.get_planet(planet_id, current_user)


@router.post(
    "",
    response_model=PlanetResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Create planet",
    description="Create a new planet",
)
async def create_planet(
    planet_data: PlanetCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PlanetResponse:
    """
    Create a new planet.

    Args:
        planet_data: Planet creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        PlanetResponse: Created planet
    """
    planet_service = PlanetService(db)
    return await planet_service.create_planet(current_user, planet_data)


@router.put(
    "/{planet_id}",
    response_model=PlanetResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update planet",
    description="Update planet information",
)
async def update_planet(
    planet_id: UUID,
    planet_data: PlanetUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PlanetResponse:
    """
    Update planet.

    Args:
        planet_id: Planet ID
        planet_data: Planet update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        PlanetResponse: Updated planet
    """
    planet_service = PlanetService(db)
    return await planet_service.update_planet(planet_id, current_user, planet_data)


@router.delete(
    "/{planet_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete planet",
    description="Delete planet (soft delete, owner only)",
)
async def delete_planet(
    planet_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete planet.

    Args:
        planet_id: Planet ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    planet_service = PlanetService(db)
    await planet_service.delete_planet(planet_id, current_user)
    return SuccessResponse(message="Planet deleted successfully")


@router.get(
    "/{planet_id}/members",
    response_model=List[PlanetMemberResponse],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get planet members",
    description="Get all members of a planet",
)
async def get_planet_members(
    planet_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[PlanetMemberResponse]:
    """
    Get all members of a planet.

    Args:
        planet_id: Planet ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[PlanetMemberResponse]: List of planet members
    """
    planet_service = PlanetService(db)
    return await planet_service.get_planet_members(planet_id, current_user)


@router.post(
    "/{planet_id}/members",
    response_model=PlanetMemberResponse,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Add planet member",
    description="Add a member to the planet",
)
async def add_planet_member(
    planet_id: UUID,
    member_data: PlanetMemberCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PlanetMemberResponse:
    """
    Add a member to the planet.

    Args:
        planet_id: Planet ID
        member_data: Member creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        PlanetMemberResponse: Created member
    """
    planet_service = PlanetService(db)
    return await planet_service.add_member(planet_id, current_user, member_data)


@router.delete(
    "/{planet_id}/members/{user_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Remove planet member",
    description="Remove a member from the planet",
)
async def remove_planet_member(
    planet_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Remove a member from the planet.

    Args:
        planet_id: Planet ID
        user_id: User ID to remove
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    planet_service = PlanetService(db)
    await planet_service.remove_member(planet_id, user_id, current_user)
    return SuccessResponse(message="Member removed successfully")


@router.put(
    "/{planet_id}/members/{user_id}/role",
    response_model=PlanetMemberResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update planet member role",
    description="Update the role of a planet member",
)
async def update_planet_member_role(
    planet_id: UUID,
    user_id: UUID,
    role_data: PlanetMemberRoleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PlanetMemberResponse:
    """
    Update the role of a planet member.

    Args:
        planet_id: Planet ID
        user_id: User ID to update
        role_data: Role update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        PlanetMemberResponse: Updated member
    """
    planet_service = PlanetService(db)
    return await planet_service.update_member_role(planet_id, user_id, role_data.role, current_user)


@router.get(
    "/{planet_id}/dashboards",
    response_model=List[DashboardResponse],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get planet dashboards",
    description="Get all dashboards in a planet",
)
async def get_planet_dashboards(
    planet_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[DashboardResponse]:
    """
    Get all dashboards in a planet.

    Args:
        planet_id: Planet ID
        skip: Number of records to skip
        limit: Maximum number of records to return
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[DashboardResponse]: List of dashboards
    """
    # Verify planet access
    planet_service = PlanetService(db)
    await planet_service.get_planet(planet_id, current_user)

    # Get dashboards
    dashboard_service = DashboardService(db)
    return await dashboard_service.get_planet_dashboards(
        planet_id, current_user, skip=skip, limit=limit
    )


@router.post(
    "/{planet_id}/switch",
    response_model=PlanetResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Switch active planet",
    description="Switch the active planet for the current user",
)
async def switch_planet(
    planet_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PlanetResponse:
    """
    Switch the active planet for the current user.

    Args:
        planet_id: Planet ID to switch to
        current_user: Current authenticated user
        db: Database session

    Returns:
        PlanetResponse: Active planet
    """
    planet_service = PlanetService(db)
    return await planet_service.switch_planet(planet_id, current_user)


@router.post(
    "/{planet_id}/star",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 400: {"model": ErrorResponse}},
    summary="Star planet",
    description="Star a planet for the current user",
)
async def star_planet(
    planet_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Star a planet for the current user.

    Args:
        planet_id: Planet ID to star
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    # Verify planet exists and user has access
    planet_service = PlanetService(db)
    await planet_service.get_planet(planet_id, current_user)

    # Star the planet
    starred_service = StarredItemService(db)
    await starred_service.star_item(current_user, planet_id, "planet")

    return SuccessResponse(message="Planet starred successfully")


@router.delete(
    "/{planet_id}/star",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}},
    summary="Unstar planet",
    description="Unstar a planet for the current user",
)
async def unstar_planet(
    planet_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Unstar a planet for the current user.

    Args:
        planet_id: Planet ID to unstar
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    # Unstar the planet (idempotent - won't error if not starred)
    starred_service = StarredItemService(db)
    await starred_service.unstar_item(current_user, planet_id, "planet")

    return SuccessResponse(message="Planet unstarred successfully")
