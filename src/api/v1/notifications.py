"""Notification endpoints — list, read, delete, and preferences management."""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.notification import NOTIFICATION_CATEGORY
from src.models.user import User
from src.schemas.notification import NotificationCount, NotificationCreate, NotificationResponse
from src.schemas.notification_preference import (
    NotificationPreferenceBatchUpdate,
    NotificationPreferenceResponse,
    PauseRequest,
)
from src.services.notification_preference_service import NotificationPreferenceService
from src.services.notification_service import NotificationService

router = APIRouter()


# ---------------------------------------------------------------------------
# Notification CRUD
# ---------------------------------------------------------------------------


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


@router.get("/categories", response_model=dict)
async def get_categories() -> dict:
    """Return the full category catalog so the frontend can build filter tabs."""
    categories = sorted(set(NOTIFICATION_CATEGORY.values()))
    return {"categories": categories}


# -- Preferences (must be before /{notification_id} to avoid route capture) --

@router.get("/preferences", response_model=List[NotificationPreferenceResponse])
async def get_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[NotificationPreferenceResponse]:
    """Get all notification preferences for the current user."""
    service = NotificationPreferenceService(db)
    return await service.get_preferences(current_user.id)


@router.put("/preferences", response_model=List[NotificationPreferenceResponse])
async def update_preferences(
    body: NotificationPreferenceBatchUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[NotificationPreferenceResponse]:
    """Batch upsert notification preferences."""
    service = NotificationPreferenceService(db)
    return await service.update_preferences(current_user.id, body.preferences)


@router.post("/preferences/pause", response_model=dict)
async def toggle_pause(
    body: PauseRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Toggle focus mode — pause or resume ALL notifications."""
    service = NotificationPreferenceService(db)
    paused = await service.toggle_pause(current_user.id, body.paused)
    return {"paused": paused, "success": True}


# -- Mark read ---------------------------------------------------------------

@router.post("/{notification_id}/read", response_model=dict)
async def mark_as_read(
    notification_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Mark a notification as read."""
    service = NotificationService(db)
    notification = await service.mark_notification_as_read(
        notification_id=notification_id, user_id=current_user.id
    )
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


# -- Delete ------------------------------------------------------------------

@router.delete("/{notification_id}", response_model=dict)
async def delete_notification(
    notification_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Delete a single notification."""
    service = NotificationService(db)
    deleted = await service.delete_notification(notification_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"deleted": 1, "success": True}


@router.delete("", response_model=dict)
async def delete_all_notifications(
    category: Optional[str] = Query(None, description="Filter by category (e.g., 'agents', 'mentions')"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Delete all notifications, optionally filtered by category."""
    service = NotificationService(db)
    count = await service.delete_notifications(user_id=current_user.id, category=category)
    return {"deleted": count, "success": True}
