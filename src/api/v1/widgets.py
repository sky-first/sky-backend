"""Widget endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.common import ErrorResponse, SuccessResponse
from src.schemas.widget import (
    WidgetDataResponse,
    WidgetExportResponse,
    WidgetFeedbackCreate,
    WidgetFeedbackResponse,
    WidgetResponse,
    WidgetUpdate,
)
from src.services.widget_service import WidgetService
from src.services.rbac_service import RBACService

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
    await RBACService(db).assert_permission(current_user, "pages.edit")
    Update widget.

    Args:
        widget_id: Widget ID
        widget_data: Widget update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        WidgetResponse: Updated widget
    """
    widget_service = WidgetService(db)
    return await widget_service.update_widget(widget_id, current_user, widget_data)


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
    await RBACService(db).assert_permission(current_user, "pages.edit")
    Delete widget.

    Args:
        widget_id: Widget ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success message
    """
    widget_service = WidgetService(db)
    await widget_service.delete_widget(widget_id, current_user)
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
    await RBACService(db).assert_permission(current_user, "pages.edit")
    Duplicate widget.

    Args:
        widget_id: Widget ID to duplicate
        current_user: Current authenticated user
        db: Database session

    Returns:
        WidgetResponse: Duplicated widget
    """
    widget_service = WidgetService(db)
    return await widget_service.duplicate_widget(widget_id, current_user)


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
    await RBACService(db).assert_permission(current_user, "pages.edit")
    Export widget data.

    Args:
        widget_id: Widget ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        WidgetExportResponse: Widget export data
    """
    widget_service = WidgetService(db)
    export_data = await widget_service.export_widget(widget_id, current_user)
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
    await RBACService(db).assert_permission(current_user, "pages.view")
    Get widget data.

    Args:
        widget_id: Widget ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        WidgetDataResponse: Widget data
    """
    widget_service = WidgetService(db)
    data = await widget_service.get_widget_data(widget_id, current_user)
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
    await RBACService(db).assert_permission(current_user, "pages.edit")
    Refresh widget data.

    Args:
        widget_id: Widget ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        WidgetDataResponse: Refreshed widget data
    """
    widget_service = WidgetService(db)
    data = await widget_service.refresh_widget_data(widget_id, current_user)
    return WidgetDataResponse(**data)


@router.post(
    "/{widget_id}/feedback",
    response_model=WidgetFeedbackResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse}},
    summary="Add widget feedback",
    description="Add or update like/dislike feedback for a widget",
)
async def add_widget_feedback(
    widget_id: UUID,
    feedback_data: WidgetFeedbackCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WidgetFeedbackResponse:
    """
    await RBACService(db).assert_permission(current_user, "pages.edit")
    Add widget feedback.

    Args:
        widget_id: Widget ID
        feedback_data: Feedback data
        current_user: Current authenticated user
        db: Database session

    Returns:
        WidgetFeedbackResponse: Created/Updated feedback
    """
    widget_service = WidgetService(db)
    return await widget_service.add_widget_feedback(widget_id, current_user, feedback_data)
