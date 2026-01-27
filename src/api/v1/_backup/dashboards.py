"""Dashboard endpoints."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.dashboard import DashboardCreate, DashboardResponse, DashboardUpdate
from src.services.dashboard_service import DashboardService

router = APIRouter()


@router.get(
    "/",
    response_model=List[DashboardResponse],
    status_code=status.HTTP_200_OK,
    summary="List dashboards",
    description="Get dashboards for a workspace",
)
async def list_dashboards(
    workspace_id: UUID = Query(..., description="Workspace ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[DashboardResponse]:
    """
    List dashboards endpoint.

    Args:
        workspace_id: Workspace ID
        skip: Number of records to skip
        limit: Maximum number of records
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[DashboardResponse]: List of dashboards
    """
    dashboard_service = DashboardService(db)
    return await dashboard_service.get_workspace_dashboards(
        workspace_id, current_user, skip=skip, limit=limit
    )


@router.post(
    "/",
    response_model=DashboardResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}},
    summary="Create dashboard",
    description="Create a new dashboard",
)
async def create_dashboard(
    dashboard_data: DashboardCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardResponse:
    """
    Create dashboard endpoint.

    Args:
        dashboard_data: Dashboard creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        DashboardResponse: Created dashboard
    """
    dashboard_service = DashboardService(db)
    return await dashboard_service.create_dashboard(current_user, dashboard_data)


@router.get(
    "/{dashboard_id}",
    response_model=DashboardResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}},
    summary="Get dashboard",
    description="Get dashboard by ID",
)
async def get_dashboard(
    dashboard_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardResponse:
    """
    Get dashboard endpoint.

    Args:
        dashboard_id: Dashboard ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        DashboardResponse: Dashboard data
    """
    dashboard_service = DashboardService(db)
    return await dashboard_service.get_dashboard(dashboard_id, current_user)


@router.put(
    "/{dashboard_id}",
    response_model=DashboardResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}},
    summary="Update dashboard",
    description="Update dashboard",
)
async def update_dashboard(
    dashboard_id: UUID,
    dashboard_data: DashboardUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardResponse:
    """
    Update dashboard endpoint.

    Args:
        dashboard_id: Dashboard ID
        dashboard_data: Dashboard update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        DashboardResponse: Updated dashboard
    """
    dashboard_service = DashboardService(db)
    return await dashboard_service.update_dashboard(dashboard_id, current_user, dashboard_data)


@router.delete(
    "/{dashboard_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}},
    summary="Delete dashboard",
    description="Delete dashboard",
)
async def delete_dashboard(
    dashboard_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete dashboard endpoint.

    Args:
        dashboard_id: Dashboard ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    dashboard_service = DashboardService(db)
    await dashboard_service.delete_dashboard(dashboard_id, current_user)
    return SuccessResponse(message="Dashboard deleted successfully")
