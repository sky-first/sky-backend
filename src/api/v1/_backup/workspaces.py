"""Workspace endpoints."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceMemberCreate,
    WorkspaceMemberResponse,
    WorkspaceResponse,
    WorkspaceSwitchRequest,
    WorkspaceUpdate,
)
from src.services.workspace_service import WorkspaceService

router = APIRouter()


@router.get(
    "/",
    response_model=List[WorkspaceResponse],
    status_code=status.HTTP_200_OK,
    summary="List workspaces",
    description="Get all workspaces for the current user",
)
async def list_workspaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[WorkspaceResponse]:
    """
    List workspaces endpoint.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[WorkspaceResponse]: List of workspaces
    """
    workspace_service = WorkspaceService(db)
    return await workspace_service.get_user_workspaces(current_user)


@router.post(
    "/",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}},
    summary="Create workspace",
    description="Create a new workspace",
)
async def create_workspace(
    workspace_data: WorkspaceCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WorkspaceResponse:
    """
    Create workspace endpoint.

    Args:
        workspace_data: Workspace creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        WorkspaceResponse: Created workspace
    """
    workspace_service = WorkspaceService(db)
    return await workspace_service.create_workspace(current_user, workspace_data)


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}},
    summary="Get workspace",
    description="Get workspace by ID",
)
async def get_workspace(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WorkspaceResponse:
    """
    Get workspace endpoint.

    Args:
        workspace_id: Workspace ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        WorkspaceResponse: Workspace data
    """
    workspace_service = WorkspaceService(db)
    return await workspace_service.get_workspace(workspace_id, current_user)


@router.put(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update workspace",
    description="Update workspace",
)
async def update_workspace(
    workspace_id: UUID,
    workspace_data: WorkspaceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WorkspaceResponse:
    """
    Update workspace endpoint.

    Args:
        workspace_id: Workspace ID
        workspace_data: Workspace update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        WorkspaceResponse: Updated workspace
    """
    workspace_service = WorkspaceService(db)
    return await workspace_service.update_workspace(workspace_id, current_user, workspace_data)


@router.delete(
    "/{workspace_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete workspace",
    description="Delete workspace",
)
async def delete_workspace(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete workspace endpoint.

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


@router.post(
    "/{workspace_id}/switch",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Switch workspace",
    description="Switch active workspace",
)
async def switch_workspace(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WorkspaceResponse:
    """
    Switch workspace endpoint.

    Args:
        workspace_id: Workspace ID to switch to
        current_user: Current authenticated user
        db: Database session

    Returns:
        WorkspaceResponse: Active workspace
    """
    workspace_service = WorkspaceService(db)
    return await workspace_service.switch_workspace(workspace_id, current_user)


@router.get(
    "/{workspace_id}/members",
    response_model=List[WorkspaceMemberResponse],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="List workspace members",
    description="Get all members of a workspace",
)
async def list_workspace_members(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[WorkspaceMemberResponse]:
    """
    List workspace members endpoint.

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
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Add workspace member",
    description="Add member to workspace",
)
async def add_workspace_member(
    workspace_id: UUID,
    member_data: WorkspaceMemberCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Add workspace member endpoint.

    Args:
        workspace_id: Workspace ID
        member_data: Member data
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    workspace_service = WorkspaceService(db)
    await workspace_service.add_member(workspace_id, current_user, member_data)
    return SuccessResponse(message="Member added successfully")


@router.delete(
    "/{workspace_id}/members/{user_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Remove workspace member",
    description="Remove member from workspace",
)
async def remove_workspace_member(
    workspace_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Remove workspace member endpoint.

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
