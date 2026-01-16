"""Notification service."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.notification_repository import NotificationRepository
from src.schemas.notification import NotificationCreate, NotificationResponse


class NotificationService:
    """Service for Notification business logic."""

    def __init__(self, db: AsyncSession):
        self.repository = NotificationRepository(db)

    async def create_notification(self, notification_in: NotificationCreate) -> NotificationResponse:
        """Create a new notification."""
        return await self.repository.create(notification_in)

    async def get_notifications(
        self,
        user_id: UUID,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
    ) -> List[NotificationResponse]:
        """Get notifications for a user."""
        return await self.repository.get_all_by_user(
            user_id=user_id, limit=limit, offset=offset, unread_only=unread_only
        )

    async def get_unread_count(self, user_id: UUID) -> int:
        """Get unread notification count."""
        return await self.repository.get_unread_count(user_id)

    async def mark_as_read(self, notification_id: UUID, user_id: UUID) -> Optional[NotificationResponse]:
        """Mark a notification as read."""
        return await self.repository.mark_as_read(notification_id, user_id)

    async def mark_all_as_read(self, user_id: UUID) -> int:
        """Mark all notifications as read."""
        return await self.repository.mark_all_as_read(user_id)
