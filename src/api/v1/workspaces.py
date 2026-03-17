"""Workspace endpoints."""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.dashboard import DashboardResponse
from src.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceMemberCreate,
    WorkspaceMemberResponse,
    WorkspaceMemberRoleUpdate,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from src.services.dashboard_service import DashboardService
from src.services.workspace_service import WorkspaceService

router = APIRouter()


@router.get(
    "",
    response_model=List[WorkspaceResponse],
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="List workspaces",
    description="Get list of workspaces for the current user",
)
async def list_workspaces(
    type: Optional[str] = Query(None, pattern="^(personal|team)$"),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[WorkspaceResponse]:
    """
    List all workspaces for the current user.

    Args:
        type: Filter by workspace type (personal|team)
        search: Search term for workspace name
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[WorkspaceResponse]: List of workspaces
    """
    workspace_service = WorkspaceService(db)
    workspaces = await workspace_service.get_user_workspaces(current_user)

    # Apply filters
    if type:
        workspaces = [w for w in workspaces if w.type == type]
    if search:
        search_lower = search.lower()
        workspaces = [w for w in workspaces if search_lower in w.name.lower()]

    return workspaces


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get workspace",
    description="Get workspace by ID",
)
async def get_workspace(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WorkspaceResponse:
    """
    Get workspace by ID.

    Args:
        workspace_id: Workspace ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        WorkspaceResponse: Workspace data
    """
    workspace_service = WorkspaceService(db)
    return await workspace_service.get_workspace(workspace_id, current_user)


@router.post(
    "",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    summary="Create workspace",
    description="Create a new workspace",
)
async def create_workspace(
    workspace_data: WorkspaceCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WorkspaceResponse:
    """
    Create a new workspace.

    Args:
        workspace_data: Workspace creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        WorkspaceResponse: Created workspace
    """
    workspace_service = WorkspaceService(db)
    return await workspace_service.create_workspace(current_user, workspace_data)


@router.put(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update workspace",
    description="Update workspace information",
)
async def update_workspace(
    workspace_id: UUID,
    workspace_data: WorkspaceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WorkspaceResponse:
    """
    Update workspace.

    Args:
        workspace_id: Workspace ID
        workspace_data: Workspace update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        WorkspaceResponse: Updated workspace
    """
    workspace_service = WorkspaceService(db)
    return await workspace_service.update_workspace(
        workspace_id, current_user, workspace_data
    )


@router.delete(
    "/{workspace_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete workspace",
    description="Delete workspace (soft delete, owner only)",
)
async def delete_workspace(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete workspace.

    Args:
        workspace_id: Workspace ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    workspace_service = WorkspaceService(db)
    await workspace_service.delete_workspace(workspace_id, current_user)
    return SuccessResponse(message="Workspace deleted successfully")


@router.get(
    "/{workspace_id}/members",
    response_model=List[WorkspaceMemberResponse],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get workspace members",
    description="Get all members of a workspace",
)
async def get_workspace_members(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[WorkspaceMemberResponse]:
    """
    Get all members of a workspace.

    Args:
        workspace_id: Workspace ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[WorkspaceMemberResponse]: List of workspace members
    """
    workspace_service = WorkspaceService(db)
    return await workspace_service.get_workspace_members(workspace_id, current_user)


@router.post(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberResponse,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Add workspace member",
    description="Add a member to the workspace",
)
async def add_workspace_member(
    workspace_id: UUID,
    member_data: WorkspaceMemberCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WorkspaceMemberResponse:
    """
    Add a member to the workspace.

    Args:
        workspace_id: Workspace ID
        member_data: Member creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        WorkspaceMemberResponse: Created member
    """
    workspace_service = WorkspaceService(db)
    return await workspace_service.add_member(workspace_id, current_user, member_data)


@router.delete(
    "/{workspace_id}/members/{user_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Remove workspace member",
    description="Remove a member from the workspace",
)
async def remove_workspace_member(
    workspace_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Remove a member from the workspace.

    Args:
        workspace_id: Workspace ID
        user_id: User ID to remove
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    workspace_service = WorkspaceService(db)
    await workspace_service.remove_member(workspace_id, user_id, current_user)
    return SuccessResponse(message="Member removed successfully")


@router.put(
    "/{workspace_id}/members/{user_id}/role",
    response_model=WorkspaceMemberResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update workspace member role",
    description="Update the role of a workspace member",
)
async def update_workspace_member_role(
    workspace_id: UUID,
    user_id: UUID,
    role_data: WorkspaceMemberRoleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WorkspaceMemberResponse:
    """
    Update the role of a workspace member.

    Args:
        workspace_id: Workspace ID
        user_id: User ID to update
        role_data: Role update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        WorkspaceMemberResponse: Updated member
    """
    workspace_service = WorkspaceService(db)
    return await workspace_service.update_member_role(
        workspace_id, user_id, role_data.role, current_user
    )


@router.get(
    "/{workspace_id}/dashboards",
    response_model=List[DashboardResponse],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get workspace dashboards",
    description="Get all dashboards in a workspace",
)
async def get_workspace_dashboards(
    workspace_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[DashboardResponse]:
    """
    Get all dashboards in a workspace.

    Args:
        workspace_id: Workspace ID
        skip: Number of records to skip
        limit: Maximum number of records to return
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[DashboardResponse]: List of dashboards
    """
    # Verify workspace access
    workspace_service = WorkspaceService(db)
    await workspace_service.get_workspace(workspace_id, current_user)

    # Get dashboards
    dashboard_service = DashboardService(db)
    return await dashboard_service.get_workspace_dashboards(
        workspace_id, current_user, skip=skip, limit=limit
    )


@router.post(
    "/{workspace_id}/switch",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Switch active workspace",
    description="Switch the active workspace for the current user",
)
async def switch_workspace(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WorkspaceResponse:
    """
    Switch the active workspace for the current user.

    Args:
        workspace_id: Workspace ID to switch to
        current_user: Current authenticated user
        db: Database session

    Returns:
        WorkspaceResponse: Active workspace
    """
    workspace_service = WorkspaceService(db)
    return await workspace_service.switch_workspace(workspace_id, current_user)
