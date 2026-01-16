"""Notification endpoints."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.schemas.notification import NotificationCount, NotificationResponse
from src.services.notification_service import NotificationService

router = APIRouter()


@router.get("", response_model=List[NotificationResponse])
async def get_notifications(
    limit: int = 50,
    offset: int = 0,
    unread_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[NotificationResponse]:
    """Get notifications for the current user."""
    service = NotificationService(db)
    return await service.get_notifications(
        user_id=current_user.id,
        limit=limit,
        offset=offset,
        unread_only=unread_only,
    )


@router.get("/unread-count", response_model=NotificationCount)
async def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> NotificationCount:
    """Get unread notification count."""
    service = NotificationService(db)
    count = await service.get_unread_count(user_id=current_user.id)
    return NotificationCount(count=count)


@router.post("/{notification_id}/read", response_model=dict)
async def mark_as_read(
    notification_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Mark a notification as read."""
    service = NotificationService(db)
    notification = await service.mark_as_read(notification_id=notification_id, user_id=current_user.id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"updated": 1, "success": True}


@router.post("/read-all", response_model=dict)
async def mark_all_as_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Mark all notifications as read."""
    service = NotificationService(db)
    count = await service.mark_all_as_read(user_id=current_user.id)
    return {"updated": count, "success": True}
