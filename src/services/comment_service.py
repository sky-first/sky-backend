"""Comment service."""

from typing import List
from uuid import UUID

from sqlalchemy import desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from src.models.comment import Comment
from src.models.notification import NotificationType
from src.schemas.comment import CommentCreate
from src.schemas.notification import NotificationCreate
from src.services.notification_service import NotificationService


class CommentService:
    """Service for managing comments."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.notification_service = NotificationService(db)

    async def create(self, user_id: UUID, comment_data: CommentCreate) -> Comment:
        """Create a new comment and trigger notifications."""
        db_comment = Comment(
            user_id=user_id,
            dashboard_id=comment_data.dashboard_id,
            widget_id=comment_data.widget_id,
            content=comment_data.content,
            mentions=[str(m) for m in comment_data.mentions],
        )
        self.db.add(db_comment)
        await self.db.commit()
        await self.db.refresh(db_comment)

        # Trigger Notifications
        # 1. Notify mentioned users
        for mentioned_user_id in comment_data.mentions:
            if mentioned_user_id != user_id:  # Don't notify self
                await self.notification_service.create(
                    NotificationCreate(
                        user_id=mentioned_user_id,
                        type=NotificationType.COMMENT_MENTION,
                        title="You were mentioned in a comment",
                        description=f"User mentioned you: {comment_data.content[:50]}...",
                        entity_type="comment",
                        entity_id=str(db_comment.id),
                        deep_link=f"/dashboards/{comment_data.dashboard_id}",
                    )
                )

        # 2. Notify dashboard owner logic (simplified/omitted for now until owner fetch is robust)

        return db_comment

    async def get_by_dashboard(self, dashboard_id: UUID) -> List[Comment]:
        """Get comments for a dashboard."""
        query = (
            select(Comment)
            .where(Comment.dashboard_id == dashboard_id)
            .order_by(desc(Comment.created_at))
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
