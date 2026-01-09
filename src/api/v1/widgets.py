"""Widget endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.dashboard import (
    WidgetDataResponse,
    WidgetExportResponse,
    WidgetResponse,
    WidgetUpdate,
)
from src.services.dashboard_service import DashboardService

router = APIRouter()


@router.put(
    "/{widget_id}",
    response_model=WidgetResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Update widget",
    description="Update widget information",
)
async def update_widget(
    widget_id: UUID,
    widget_data: WidgetUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WidgetResponse:
    """
    Update widget.

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
    "/{widget_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Delete widget",
    description="Delete widget",
)
async def delete_widget(
    widget_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SuccessResponse:
    """
    Delete widget.

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


@router.post(
    "/{widget_id}/duplicate",
    response_model=WidgetResponse,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Duplicate widget",
    description="Create a duplicate of the widget",
)
async def duplicate_widget(
    widget_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WidgetResponse:
    """
    Duplicate widget.

    Args:
        widget_id: Widget ID to duplicate
        current_user: Current authenticated user
        db: Database session

    Returns:
        WidgetResponse: Duplicated widget
    """
    dashboard_service = DashboardService(db)
    return await dashboard_service.duplicate_widget(widget_id, current_user)


@router.post(
    "/{widget_id}/export",
    response_model=WidgetExportResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Export widget",
    description="Export widget data",
)
async def export_widget(
    widget_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WidgetExportResponse:
    """
    Export widget data.

    Args:
        widget_id: Widget ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        WidgetExportResponse: Widget export data
    """
    dashboard_service = DashboardService(db)
    export_data = await dashboard_service.export_widget(widget_id, current_user)
    return WidgetExportResponse(**export_data)


@router.get(
    "/{widget_id}/data",
    response_model=WidgetDataResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Get widget data",
    description="Get widget data",
)
async def get_widget_data(
    widget_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WidgetDataResponse:
    """
    Get widget data.

    Args:
        widget_id: Widget ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        WidgetDataResponse: Widget data
    """
    dashboard_service = DashboardService(db)
    data = await dashboard_service.get_widget_data(widget_id, current_user)
    return WidgetDataResponse(**data)


@router.post(
    "/{widget_id}/refresh",
    response_model=WidgetDataResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Refresh widget data",
    description="Force refresh widget data",
)
async def refresh_widget_data(
    widget_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WidgetDataResponse:
    """
    Refresh widget data.

    Args:
        widget_id: Widget ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        WidgetDataResponse: Refreshed widget data
    """
    dashboard_service = DashboardService(db)
    data = await dashboard_service.refresh_widget_data(widget_id, current_user)
    return WidgetDataResponse(**data)
