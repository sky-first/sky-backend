"""User endpoints."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.user import (
    DemoDataRemovedResponse,
    DemoDataStatusResponse,
    ExploreDemoDataResponse,
    OnboardingUpdate,
    UserCreate,
    UserInviteRequest,
    UserPermissionsResponse,
    UserPermissionsUpdate,
    UserResponse,
    UserUpdate,
)
from src.services.demo_service import DemoService
from src.services.rbac_service import RBACService
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
    # Users list is needed by anyone who manages crew/space members.
    # admin.users.manage is false for all roles by default (reserved for
    # platform-level user admin). For listing, we allow any authenticated
    # user with a non-guest role — the service layer filters appropriately.
    # The RBAC gate here just blocks guest/viewer from listing all users.
    await RBACService(db).assert_permission(current_user, "crews.members.manage")
    user_service = UserService(db)
    return await user_service.list_users(current_user, skip=skip, limit=limit)


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current user",
    description="Return the authenticated user's own profile.",
)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.put(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    responses={403: {"model": ErrorResponse}},
    summary="Update current user",
    description="Update current authenticated user information",
)
async def update_me(
    user_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    """
    Update current user.

    Args:
        user_data: User update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        UserResponse: Updated user
    """
    user_service = UserService(db)
    return await user_service.update_user(current_user.id, user_data, current_user)


@router.patch(
    "/me/onboarding",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    responses={403: {"model": ErrorResponse}},
    summary="Update onboarding progress",
    description="Update onboarding step or version for current user",
)
async def update_my_onboarding(
    onboarding_data: OnboardingUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    """
    Update my onboarding progress.

    Args:
        onboarding_data: Onboarding update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        UserResponse: Updated user
    """
    user_service = UserService(db)
    return await user_service.update_onboarding(
        current_user.id, onboarding_data.step, onboarding_data.version, current_user
    )


@router.post(
    "/me/onboarding/explore-demo-data",
    response_model=ExploreDemoDataResponse,
    status_code=status.HTTP_200_OK,
    responses={403: {"model": ErrorResponse}},
    summary="Provision a personal demo workspace for the current user",
    description=(
        "Used by the first-login modal that asks SSO users 'do you want "
        "to explore with sample data?'. Creates (or returns the existing) "
        "'Demo Sky' Space owned by the current user, binds the demo "
        "dataset Connections, and seeds the Glossary, Metrics, "
        "Relationships and 3 Agents — same baseline a public /demo "
        "visitor receives, minus the TTL.\n\n"
        "Idempotent: re-running on a user who already has a 'Demo Sky' "
        "space returns it as-is and only fills in any missing seed."
    ),
)
async def explore_demo_data(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ExploreDemoDataResponse:
    """Provision a sample workspace for the current authenticated user."""
    service = DemoService(db)
    result = await service.provision_for_existing_user(current_user)
    return ExploreDemoDataResponse(**result)


@router.get(
    "/me/onboarding/explore-demo-data",
    response_model=DemoDataStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Status of the current user's personal demo workspace",
    description=(
        "Reports whether the current user has a personal 'Demo Sky' "
        "workspace (and what's seeded inside it). Used by the FE banner "
        "to decide between rendering the first-login modal vs the "
        "'Remove sample data' button."
    ),
)
async def explore_demo_data_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DemoDataStatusResponse:
    service = DemoService(db)
    return DemoDataStatusResponse(
        **(await service.get_personal_demo_status(current_user))
    )


@router.delete(
    "/me/onboarding/explore-demo-data",
    response_model=DemoDataRemovedResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove the current user's personal demo workspace",
    description=(
        "Hard-deletes the user's personal 'Demo Sky' Space (created "
        "via POST explore-demo-data) and all its content — seeded "
        "metrics, glossary terms, relationships, agents, and the "
        "Space itself with cascade. Bypasses the platform-level "
        "RBAC for Space deletion: the user opted into this Space "
        "and must always be able to clean it up regardless of their "
        "tenant role.\n\n"
        "Idempotent: returns ``removed=False`` when the user has no "
        "Demo Sky to delete."
    ),
)
async def delete_explore_demo_data(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DemoDataRemovedResponse:
    service = DemoService(db)
    return DemoDataRemovedResponse(
        **(await service.remove_personal_demo_workspace(current_user))
    )


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


@router.post(
    "/{user_id}/restore",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Restore a soft-deleted user",
    description=(
        "Restores a previously deleted user (clears deleted_at). Same "
        "permission as delete — admins who can deactivate can reactivate. "
        "Idempotent: calling on a non-deleted user is a no-op."
    ),
)
async def restore_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    user_service = UserService(db)
    return await user_service.restore_user(user_id, current_user)


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
