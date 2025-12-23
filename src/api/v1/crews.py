"""Crew endpoints."""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.crew import (
    CrewCreate,
    CrewMemberCreate,
    CrewMemberResponse,
    CrewMemberUpdate,
    CrewResponse,
    CrewUpdate,
)
from src.services.crew_service import CrewService

router = APIRouter()


@router.get(
    "",
    response_model=List[CrewResponse],
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="List crews",
    description="Get list of crews",
)
async def list_crews(
    space_id: Optional[UUID] = Query(None, description="Filter by space ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[CrewResponse]:
    """
    List crews.

    Args:
        space_id: Optional space ID to filter
        skip: Number of records to skip
        limit: Maximum number of records to return
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[CrewResponse]: List of crews
    """
    crew_service = CrewService(db)
    return await crew_service.list_crews(current_user, space_id=space_id, skip=skip, limit=limit)


@router.get(
    "/{crew_id}",
    response_model=CrewResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get crew",
    description="Get crew by ID",
)
async def get_crew(
    crew_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> CrewResponse:
    """
    Get crew by ID.

    Args:
        crew_id: Crew ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        CrewResponse: Crew data
    """
    crew_service = CrewService(db)
    return await crew_service.get_crew(crew_id, current_user)


@router.post(
    "",
    response_model=CrewResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Create crew",
    description="Create a new crew",
)
async def create_crew(
    crew_data: CrewCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> CrewResponse:
    """
    Create a new crew.

    Args:
        crew_data: Crew creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        CrewResponse: Created crew
    """
    crew_service = CrewService(db)
    return await crew_service.create_crew(current_user, crew_data)


@router.put(
    "/{crew_id}",
    response_model=CrewResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update crew",
    description="Update crew information",
)
async def update_crew(
    crew_id: UUID,
    crew_data: CrewUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> CrewResponse:
    """
    Update crew.

    Args:
        crew_id: Crew ID
        crew_data: Crew update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        CrewResponse: Updated crew
    """
    crew_service = CrewService(db)
    return await crew_service.update_crew(crew_id, current_user, crew_data)


@router.delete(
    "/{crew_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete crew",
    description="Delete crew (soft delete)",
)
async def delete_crew(
    crew_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete crew.

    Args:
        crew_id: Crew ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    crew_service = CrewService(db)
    await crew_service.delete_crew(crew_id, current_user)
    return SuccessResponse(message="Crew deleted successfully")


@router.get(
    "/{crew_id}/members",
    response_model=List[CrewMemberResponse],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get crew members",
    description="Get all members in a crew",
)
async def get_crew_members(
    crew_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[CrewMemberResponse]:
    """
    Get all members in a crew.

    Args:
        crew_id: Crew ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[CrewMemberResponse]: List of crew members
    """
    crew_service = CrewService(db)
    return await crew_service.get_crew_members(crew_id, current_user)


@router.post(
    "/{crew_id}/members",
    response_model=CrewMemberResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Add crew member",
    description="Add a member to a crew",
)
async def add_crew_member(
    crew_id: UUID,
    member_data: CrewMemberCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> CrewMemberResponse:
    """
    Add member to crew.

    Args:
        crew_id: Crew ID
        member_data: Member data
        current_user: Current authenticated user
        db: Database session

    Returns:
        CrewMemberResponse: Created member
    """
    crew_service = CrewService(db)
    return await crew_service.add_crew_member(crew_id, current_user, member_data)


@router.delete(
    "/{crew_id}/members/{user_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Remove crew member",
    description="Remove a member from a crew",
)
async def remove_crew_member(
    crew_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Remove member from crew.

    Args:
        crew_id: Crew ID
        user_id: User ID to remove
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    crew_service = CrewService(db)
    await crew_service.remove_crew_member(crew_id, user_id, current_user)
    return SuccessResponse(message="Member removed successfully")


@router.put(
    "/{crew_id}/members/{user_id}/role",
    response_model=CrewMemberResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update crew member role",
    description="Update the role of a crew member",
)
async def update_crew_member_role(
    crew_id: UUID,
    user_id: UUID,
    role_data: CrewMemberUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> CrewMemberResponse:
    """
    Update crew member role.

    Args:
        crew_id: Crew ID
        user_id: User ID of the member
        role_data: New role
        current_user: Current authenticated user
        db: Database session

    Returns:
        CrewMemberResponse: Updated member
    """
    crew_service = CrewService(db)
    return await crew_service.update_crew_member_role(
        crew_id, user_id, role_data, current_user
    )

