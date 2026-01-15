"""Notification API endpoints."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from src.api.deps import get_current_user
from src.config.database import get_db
from src.models.user import User
from src.schemas.notification import NotificationResponse
from src.services.notification_service import NotificationService

router = APIRouter()


@router.get("/", response_model=List[NotificationResponse])
async def list_notifications(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """List notifications for the current user."""
    service = NotificationService(db)
    return await service.get_for_user(
        user_id=current_user.id, limit=limit, offset=offset, unread_only=unread_only
    )


@router.get("/unread-count")
async def count_unread_notifications(
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Count unread notifications."""
    service = NotificationService(db)
    count = await service.count_unread(current_user.id)
    return {"count": count}


@router.post("/read-all")
async def mark_all_as_read(
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Mark all notifications as read."""
    service = NotificationService(db)
    count = await service.mark_all_as_read(current_user.id)
    return {"updated": count}


@router.post("/{notification_id}/read")
async def mark_as_read(
    notification_id: UUID,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Mark a specific notification as read."""
    service = NotificationService(db)
    # Security check: ensures we only update if it belongs to user
    count = await service.mark_as_read(current_user.id, [notification_id])
    return {"updated": count, "success": count > 0}
