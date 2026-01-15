"""Notification service."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import desc, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from src.models.notification import Notification, NotificationType
from src.schemas.notification import NotificationCreate


class NotificationService:
    """Service for managing notifications."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, notification: NotificationCreate) -> Notification:
        """Create a new persistent notification."""
        db_notification = Notification(
            user_id=notification.user_id,
            space_id=notification.space_id,
            type=notification.type,
            title=notification.title,
            description=notification.description,
            entity_type=notification.entity_type,
            entity_id=notification.entity_id,
            deep_link=notification.deep_link,
        )
        self.db.add(db_notification)
        await self.db.commit()
        await self.db.refresh(db_notification)
        return db_notification

    async def get_for_user(
        self, user_id: UUID, limit: int = 50, offset: int = 0, unread_only: bool = False
    ) -> List[Notification]:
        """Get notifications for a user."""
        query = select(Notification).where(Notification.user_id == user_id)

        if unread_only:
            query = query.where(Notification.is_read == False)

        query = query.order_by(desc(Notification.created_at)).limit(limit).offset(offset)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_unread(self, user_id: UUID) -> int:
        """Count unread notifications for a user."""
        query = select(Notification).where(
            Notification.user_id == user_id, Notification.is_read == False
        )
        # Efficient count
        from sqlalchemy import func
        query = select(func.count()).select_from(query.subquery())
        result = await self.db.execute(query)
        return result.scalar_one()

    async def mark_as_read(self, user_id: UUID, notification_ids: List[UUID]) -> int:
        """Mark specific notifications as read."""
        if not notification_ids:
            return 0
            
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.id.in_(notification_ids),
                Notification.is_read == False,
            )
            .values(is_read=True, read_at=datetime.utcnow())
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount

    async def mark_all_as_read(self, user_id: UUID) -> int:
        """Mark all notifications as read for a user."""
        stmt = (
            update(Notification)
            .where(Notification.user_id == user_id, Notification.is_read == False)
            .values(is_read=True, read_at=datetime.utcnow())
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount

    async def delete_all(self, user_id: UUID) -> int:
        """Delete all notifications for a user (cleanup)."""
        from sqlalchemy import delete
        stmt = delete(Notification).where(Notification.user_id == user_id)
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount
