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

    async def create_notification(
        self, notification_in: NotificationCreate
    ) -> NotificationResponse:
        """Create a new notification."""
        return await self.repository.create(notification_in)

    async def create(self, notification_in: NotificationCreate) -> NotificationResponse:
        """Alias for create_notification to match tests."""
        return await self.create_notification(notification_in)

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

    async def get_for_user(
        self,
        user_id: UUID,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
    ) -> List[NotificationResponse]:
        """Alias for get_notifications to match tests."""
        return await self.get_notifications(user_id, limit, offset, unread_only)

    async def get_unread_count(self, user_id: UUID) -> int:
        """Get unread notification count."""
        return await self.repository.get_unread_count(user_id)

    async def mark_as_read(self, user_id: UUID, notification_ids: List[UUID]) -> int:
        """Mark notifications as read. Compatible with test signatures."""
        count = 0
        for notif_id in notification_ids:
            res = await self.repository.mark_as_read(notif_id, user_id)
            if res:
                count += 1
        return count

    async def mark_notification_as_read(
        self, notification_id: UUID, user_id: UUID
    ) -> Optional[NotificationResponse]:
        """Mark a single notification as read."""
        return await self.repository.mark_as_read(notification_id, user_id)

    async def mark_all_as_read(self, user_id: UUID) -> int:
        """Mark all notifications as read."""
        return await self.repository.mark_all_as_read(user_id)
