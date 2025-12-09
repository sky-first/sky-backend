"""Widget endpoints."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.dashboard import WidgetCreate, WidgetResponse, WidgetUpdate
from src.services.dashboard_service import DashboardService

router = APIRouter()


@router.get(
    "/{dashboard_id}/widgets",
    response_model=List[WidgetResponse],
    status_code=status.HTTP_200_OK,
    summary="List dashboard widgets",
    description="Get all widgets for a dashboard",
)
async def list_widgets(
    dashboard_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[WidgetResponse]:
    """
    List widgets endpoint.

    Args:
        dashboard_id: Dashboard ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        List[WidgetResponse]: List of widgets
    """
    dashboard_service = DashboardService(db)
    return await dashboard_service.get_dashboard_widgets(dashboard_id, current_user)


@router.post(
    "/{dashboard_id}/widgets",
    response_model=WidgetResponse,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}},
    summary="Create widget",
    description="Create a new widget",
)
async def create_widget(
    dashboard_id: UUID,
    widget_data: WidgetCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WidgetResponse:
    """
    Create widget endpoint.

    Args:
        dashboard_id: Dashboard ID
        widget_data: Widget creation data (dashboard_id will be overridden)
        current_user: Current authenticated user
        db: Database session

    Returns:
        WidgetResponse: Created widget
    """
    widget_data.dashboard_id = dashboard_id
    dashboard_service = DashboardService(db)
    return await dashboard_service.create_widget(current_user, widget_data)


@router.get(
    "/widgets/{widget_id}",
    response_model=WidgetResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}},
    summary="Get widget",
    description="Get widget by ID",
)
async def get_widget(
    widget_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WidgetResponse:
    """
    Get widget endpoint.

    Args:
        widget_id: Widget ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        WidgetResponse: Widget data
    """
    dashboard_service = DashboardService(db)
    return await dashboard_service.get_widget(widget_id, current_user)


@router.put(
    "/widgets/{widget_id}",
    response_model=WidgetResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}},
    summary="Update widget",
    description="Update widget",
)
async def update_widget(
    widget_id: UUID,
    widget_data: WidgetUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WidgetResponse:
    """
    Update widget endpoint.

    Args:
        widget_id: Widget ID
        widget_data: Widget update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        WidgetResponse: Updated widget
    """
    dashboard_service = DashboardService(db)
    return await dashboard_service.update_widget(widget_id, current_user, widget_data)


@router.delete(
    "/widgets/{widget_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}},
    summary="Delete widget",
    description="Delete widget",
)
async def delete_widget(
    widget_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete widget endpoint.

    Args:
        widget_id: Widget ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    dashboard_service = DashboardService(db)
    await dashboard_service.delete_widget(widget_id, current_user)
    return SuccessResponse(message="Widget deleted successfully")


@router.get(
    "/widgets/{widget_id}/data",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}},
    summary="Get widget data",
    description="Get widget data (may trigger refresh)",
)
async def get_widget_data(
    widget_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Get widget data endpoint.

    Args:
        widget_id: Widget ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        dict: Widget data
    """
    dashboard_service = DashboardService(db)
    widget = await dashboard_service.get_widget(widget_id, current_user)
    return widget.data or {}


@router.post(
    "/widgets/{widget_id}/refresh",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}},
    summary="Refresh widget data",
    description="Force refresh of widget data",
)
async def refresh_widget(
    widget_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Refresh widget endpoint.

    Args:
        widget_id: Widget ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    # TODO: Implement widget data refresh logic
    return SuccessResponse(message="Widget refresh triggered")

