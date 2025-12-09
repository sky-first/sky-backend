"""Dashboard endpoints."""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.dashboard import (
    DashboardCreate,
    DashboardDuplicateRequest,
    DashboardExportResponse,
    DashboardResponse,
    DashboardUpdate,
    WidgetCreate,
    WidgetResponse,
)
from src.services.dashboard_service import DashboardService

router = APIRouter()


@router.get(
    "",
    response_model=List[DashboardResponse],
    status_code=status.HTTP_200_OK,
    responses={401: {"model": ErrorResponse}},
    summary="List dashboards",
    description="Get list of dashboards (optionally filtered by workspace)",
)
async def list_dashboards(
    planet_id: Optional[UUID] = Query(None, description="Filter by planet ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[DashboardResponse]:
    """
    List dashboards.

    Args:
        planet_id: Optional planet ID to filter
        skip: Number of records to skip
        limit: Maximum number of records to return
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[DashboardResponse]: List of dashboards
    """
    dashboard_service = DashboardService(db)
    return await dashboard_service.list_dashboards(
        current_user, planet_id=planet_id, skip=skip, limit=limit
    )


@router.get(
    "/{dashboard_id}",
    response_model=DashboardResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get dashboard",
    description="Get dashboard by ID",
)
async def get_dashboard(
    dashboard_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardResponse:
    """
    Get dashboard by ID.

    Args:
        dashboard_id: Dashboard ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        DashboardResponse: Dashboard data
    """
    dashboard_service = DashboardService(db)
    return await dashboard_service.get_dashboard(dashboard_id, current_user)


@router.post(
    "",
    response_model=DashboardResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Create dashboard",
    description="Create a new dashboard",
)
async def create_dashboard(
    dashboard_data: DashboardCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardResponse:
    """
    Create a new dashboard.

    Args:
        dashboard_data: Dashboard creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        DashboardResponse: Created dashboard
    """
    dashboard_service = DashboardService(db)
    return await dashboard_service.create_dashboard(current_user, dashboard_data)


@router.put(
    "/{dashboard_id}",
    response_model=DashboardResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update dashboard",
    description="Update dashboard information",
)
async def update_dashboard(
    dashboard_id: UUID,
    dashboard_data: DashboardUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardResponse:
    """
    Update dashboard.

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
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete dashboard",
    description="Delete dashboard (soft delete)",
)
async def delete_dashboard(
    dashboard_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete dashboard.

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


@router.get(
    "/{dashboard_id}/widgets",
    response_model=List[WidgetResponse],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get dashboard widgets",
    description="Get all widgets in a dashboard",
)
async def get_dashboard_widgets(
    dashboard_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[WidgetResponse]:
    """
    Get all widgets in a dashboard.

    Args:
        dashboard_id: Dashboard ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[WidgetResponse]: List of widgets
    """
    dashboard_service = DashboardService(db)
    # Verify dashboard exists
    await dashboard_service.get_dashboard(dashboard_id, current_user)
    return await dashboard_service.get_dashboard_widgets(dashboard_id, current_user)


@router.post(
    "/{dashboard_id}/widgets",
    response_model=WidgetResponse,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Create widget",
    description="Create a new widget in a dashboard",
)
async def create_widget(
    dashboard_id: UUID,
    widget_data: WidgetCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WidgetResponse:
    """
    Create a new widget in a dashboard.

    Args:
        dashboard_id: Dashboard ID
        widget_data: Widget creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        WidgetResponse: Created widget
    """
    dashboard_service = DashboardService(db)
    # Ensure widget is created for the correct dashboard
    widget_data.dashboard_id = dashboard_id
    return await dashboard_service.create_widget(current_user, widget_data)


@router.get(
    "/{dashboard_id}/export",
    response_model=DashboardExportResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Export dashboard",
    description="Export dashboard with all widgets and connections",
)
async def export_dashboard(
    dashboard_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardExportResponse:
    """
    Export dashboard.

    Args:
        dashboard_id: Dashboard ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        DashboardExportResponse: Dashboard export data
    """
    dashboard_service = DashboardService(db)
    return await dashboard_service.export_dashboard(dashboard_id, current_user)


@router.post(
    "/{dashboard_id}/duplicate",
    response_model=DashboardResponse,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Duplicate dashboard",
    description="Create a duplicate of the dashboard with all widgets",
)
async def duplicate_dashboard(
    dashboard_id: UUID,
    duplicate_data: Optional[DashboardDuplicateRequest] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardResponse:
    """
    Duplicate dashboard.

    Args:
        dashboard_id: Dashboard ID to duplicate
        duplicate_data: Optional duplicate configuration
        current_user: Current authenticated user
        db: Database session

    Returns:
        DashboardResponse: Duplicated dashboard
    """
    dashboard_service = DashboardService(db)
    return await dashboard_service.duplicate_dashboard(dashboard_id, current_user, duplicate_data)


@router.post(
    "/{dashboard_id}/lock",
    response_model=DashboardResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Lock dashboard",
    description="Lock dashboard to prevent modifications",
)
async def lock_dashboard(
    dashboard_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardResponse:
    """
    Lock dashboard.

    Args:
        dashboard_id: Dashboard ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        DashboardResponse: Locked dashboard
    """
    dashboard_service = DashboardService(db)
    return await dashboard_service.lock_dashboard(dashboard_id, current_user)


@router.post(
    "/{dashboard_id}/unlock",
    response_model=DashboardResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Unlock dashboard",
    description="Unlock dashboard to allow modifications",
)
async def unlock_dashboard(
    dashboard_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardResponse:
    """
    Unlock dashboard.

    Args:
        dashboard_id: Dashboard ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        DashboardResponse: Unlocked dashboard
    """
    dashboard_service = DashboardService(db)
    return await dashboard_service.unlock_dashboard(dashboard_id, current_user)

