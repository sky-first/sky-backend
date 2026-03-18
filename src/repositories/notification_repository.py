"""Notification repository."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.notification import Notification
from src.schemas.notification import NotificationCreate


class NotificationRepository:
    """Repository for Notification."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, notification: NotificationCreate) -> Notification:
        """Create a new notification."""
        db_notification = Notification(**notification.model_dump())
        self.db.add(db_notification)
        await self.db.commit()
        await self.db.refresh(db_notification)
        return db_notification

    async def get_all_by_user(
        self,
        user_id: UUID,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
    ) -> List[Notification]:
        """Get all notifications for a user."""
        stmt = select(Notification).where(Notification.user_id == user_id)

        if unread_only:
            stmt = stmt.where(Notification.is_read == False)  # noqa: E712

        stmt = stmt.order_by(desc(Notification.created_at)).offset(offset).limit(limit)

        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_unread_count(self, user_id: UUID) -> int:
        """Get unread notification count for a user."""
        stmt = select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712
        )
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def mark_as_read(self, notification_id: UUID, user_id: UUID) -> Optional[Notification]:
        """Mark a notification as read."""
        stmt = select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user_id
        )
        result = await self.db.execute(stmt)
        db_notification = result.scalar_one_or_none()

        if db_notification:
            db_notification.is_read = True
            db_notification.read_at = datetime.utcnow()
            await self.db.commit()
            await self.db.refresh(db_notification)

        return db_notification

    async def mark_all_as_read(self, user_id: UUID) -> int:
        """Mark all notifications as read for a user."""
        stmt = (
            update(Notification)
            .where(Notification.user_id == user_id, Notification.is_read == False)  # noqa: E712
            .values(is_read=True, read_at=datetime.utcnow())
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount
