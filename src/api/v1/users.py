"""User endpoints."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.user import (
    UserCreate,
    UserInviteRequest,
    UserPermissionsResponse,
    UserPermissionsUpdate,
    UserResponse,
    UserUpdate,
)
from src.services.user_service import UserService

router = APIRouter()


@router.get(
    "",
    response_model=List[UserResponse],
    status_code=status.HTTP_200_OK,
    responses={403: {"model": ErrorResponse}},
    summary="List users",
    description="Get list of all users (admin only)",
)
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[UserResponse]:
    """
    List all users.

    Args:
        skip: Number of records to skip
        limit: Maximum number of records to return
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[UserResponse]: List of users
    """
    user_service = UserService(db)
    return await user_service.list_users(current_user, skip=skip, limit=limit)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get user",
    description="Get user by ID",
)
async def get_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    """
    Get user by ID.

    Args:
        user_id: User ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        UserResponse: User data
    """
    user_service = UserService(db)
    return await user_service.get_user(user_id, current_user)


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Create user",
    description="Create a new user (admin only)",
)
async def create_user(
    user_data: UserCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    """
    Create a new user.

    Args:
        user_data: User creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        UserResponse: Created user
    """
    user_service = UserService(db)
    return await user_service.create_user(user_data, current_user)


@router.put(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update user",
    description="Update user information",
)
async def update_user(
    user_id: UUID,
    user_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    """
    Update user.

    Args:
        user_id: User ID
        user_data: User update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        UserResponse: Updated user
    """
    user_service = UserService(db)
    return await user_service.update_user(user_id, user_data, current_user)


@router.delete(
    "/{user_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete user",
    description="Delete user (soft delete, admin only)",
)
async def delete_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete user.

    Args:
        user_id: User ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    user_service = UserService(db)
    await user_service.delete_user(user_id, current_user)
    return SuccessResponse(message="User deleted successfully")


@router.get(
    "/{user_id}/permissions",
    response_model=UserPermissionsResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get user permissions",
    description="Get user permissions based on role",
)
async def get_user_permissions(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UserPermissionsResponse:
    """
    Get user permissions.

    Args:
        user_id: User ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        UserPermissionsResponse: User permissions
    """
    user_service = UserService(db)
    permissions = await user_service.get_user_permissions(user_id, current_user)

    # Get user to return role
    user = await user_service.get_user(user_id, current_user)

    return UserPermissionsResponse(permissions=permissions, role=user.role)


@router.put(
    "/{user_id}/permissions",
    response_model=UserPermissionsResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update user permissions",
    description="Update user permissions by changing role (admin only)",
)
async def update_user_permissions(
    user_id: UUID,
    permissions_data: UserPermissionsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UserPermissionsResponse:
    """
    Update user permissions.

    Args:
        user_id: User ID
        permissions_data: Permissions update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        UserPermissionsResponse: Updated permissions
    """
    user_service = UserService(db)
    permissions = await user_service.update_user_permissions(
        user_id, permissions_data.model_dump(), current_user
    )

    # Get user to return role
    user = await user_service.get_user(user_id, current_user)

    return UserPermissionsResponse(permissions=permissions, role=user.role)


@router.post(
    "/{user_id}/invite",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Invite user",
    description="Send invitation email to user (admin only)",
)
async def invite_user(
    user_id: UUID,
    invite_data: UserInviteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Invite user.

    Args:
        user_id: User ID
        invite_data: Invite data
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    user_service = UserService(db)
    await user_service.invite_user(user_id, invite_data.model_dump(), current_user)
    return SuccessResponse(message="Invitation sent successfully")
