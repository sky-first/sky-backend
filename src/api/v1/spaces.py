"""Space endpoints."""

import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.crew import Crew
from src.models.space import SpaceConnection
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.crew import CrewResponse
from src.schemas.space import (
    SpaceCreate,
    SpaceMemberCreate,
    SpaceMemberResponse,
    SpaceResponse,
    SpaceUpdate,
)
from src.services.space_service import SpaceService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get(
    "",
    response_model=List[SpaceResponse],
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="List spaces",
    description="Get list of spaces",
)
async def list_spaces(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[SpaceResponse]:
    """
    List spaces.

    Args:
        skip: Number of records to skip
        limit: Maximum number of records to return
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[SpaceResponse]: List of spaces
    """
    space_service = SpaceService(db)
    return await space_service.list_spaces(current_user, skip=skip, limit=limit)


@router.get(
    "/{space_id}",
    response_model=SpaceResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get space",
    description="Get space by ID",
)
async def get_space(
    space_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SpaceResponse:
    """
    Get space by ID.

    Args:
        space_id: Space ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SpaceResponse: Space data
    """
    space_service = SpaceService(db)
    return await space_service.get_space(space_id, current_user)


@router.post(
    "",
    response_model=SpaceResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Create space",
    description="Create a new space",
)
async def create_space(
    space_data: SpaceCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SpaceResponse:
    """
    Create a new space.

    Args:
        space_data: Space creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        SpaceResponse: Created space
    """
    space_service = SpaceService(db)
    logger.info(
        "[spaces:create] request user_id=%s name=%r description=%r",
        str(current_user.id),
        space_data.name,
        getattr(space_data, "description", None),
    )
    space = await space_service.create_space(current_user, space_data)
    logger.info(
        "[spaces:create] created user_id=%s space_id=%s name=%r",
        str(current_user.id),
        str(space.id),
        space.name,
    )
    return space


@router.put(
    "/{space_id}",
    response_model=SpaceResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update space",
    description="Update space information",
)
async def update_space(
    space_id: UUID,
    space_data: SpaceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SpaceResponse:
    """
    Update space.

    Args:
        space_id: Space ID
        space_data: Space update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        SpaceResponse: Updated space
    """
    space_service = SpaceService(db)
    logger.info(
        "[spaces:update] request user_id=%s space_id=%s updates=%s",
        str(current_user.id),
        str(space_id),
        space_data.model_dump(exclude_unset=True),
    )
    space = await space_service.update_space(space_id, current_user, space_data)
    logger.info(
        "[spaces:update] updated user_id=%s space_id=%s name=%r",
        str(current_user.id),
        str(space.id),
        space.name,
    )
    return space


@router.delete(
    "/{space_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete space",
    description="Delete space (soft delete)",
)
async def delete_space(
    space_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete space.

    Args:
        space_id: Space ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    space_service = SpaceService(db)
    logger.info(
        "[spaces:delete] request user_id=%s space_id=%s",
        str(current_user.id),
        str(space_id),
    )
    await space_service.delete_space(space_id, current_user)
    logger.info(
        "[spaces:delete] deleted user_id=%s space_id=%s",
        str(current_user.id),
        str(space_id),
    )
    return SuccessResponse(message="Space deleted successfully")


@router.get(
    "/{space_id}/crews",
    response_model=List[CrewResponse],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get space crews",
    description="Get all crews in a space",
)
async def get_space_crews(
    space_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[CrewResponse]:
    """
    Get all crews in a space.

    Args:
        space_id: Space ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[CrewResponse]: List of crews
    """
    space_service = SpaceService(db)
    crews = await space_service.get_space_crews(space_id, current_user)
    return [CrewResponse.model_validate(c) for c in crews]


@router.get(
    "/{space_id}/connections",
    response_model=List[dict],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get space connections",
    description="Get all connections in a space",
)
async def get_space_connections(
    space_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[dict]:
    """
    Get all connections in a space.

    Args:
        space_id: Space ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[dict]: List of connections
    """
    space_service = SpaceService(db)
    connections = await space_service.get_space_connections(space_id, current_user)
    return [{"space_id": str(c.space_id), "connection_id": str(c.connection_id)} for c in connections]


@router.get(
    "/{space_id}/members",
    response_model=List[SpaceMemberResponse],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get space members",
    description="Get all members of a space",
)
async def get_space_members(
    space_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[SpaceMemberResponse]:
    """
    Get all members of a space.

    Args:
        space_id: Space ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[SpaceMemberResponse]: List of members
    """
    space_service = SpaceService(db)
    return await space_service.get_space_members(space_id, current_user)


@router.post(
    "/{space_id}/members",
    response_model=SpaceMemberResponse,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 400: {"model": ErrorResponse}},
    summary="Add space member",
    description="Add a member to a space",
)
async def add_space_member(
    space_id: UUID,
    member_data: SpaceMemberCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SpaceMemberResponse:
    """
    Add member to space.

    Args:
        space_id: Space ID
        member_data: Member data
        current_user: Current authenticated user
        db: Database session

    Returns:
        SpaceMemberResponse: Created member
    """
    space_service = SpaceService(db)
    return await space_service.add_space_member(space_id, current_user, member_data)


@router.delete(
    "/{space_id}/members/{user_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Remove space member",
    description="Remove a member from a space",
)
async def remove_space_member(
    space_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Remove member from space.

    Args:
        space_id: Space ID
        user_id: User ID to remove
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    space_service = SpaceService(db)
    await space_service.remove_space_member(space_id, user_id, current_user)
    return SuccessResponse(message="Member removed successfully")


@router.get(
    "/{space_id}/tables",
    response_model=List[dict],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get space tables",
    description="Get all tables from connections in a space",
)
async def get_space_tables(
    space_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[dict]:
    """
    Get all tables from connections in a space.

    Args:
        space_id: Space ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[dict]: List of tables with connection info
    """
    space_service = SpaceService(db)
    return await space_service.get_space_tables(space_id, current_user)

