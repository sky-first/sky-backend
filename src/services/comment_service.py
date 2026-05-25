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
            page_id=comment_data.page_id,
            widget_id=comment_data.widget_id,
            content=comment_data.content,
            mentions=[str(m) for m in comment_data.mentions],
        )
        self.db.add(db_comment)
        await self.db.commit()
        await self.db.refresh(db_comment)

        # Trigger Notifications
        # 1. Notify mentioned users
        #
        # Deep-link shape: the frontend route is `/dashboard?id=<id>`
        # (singular — there is no `/dashboards/<id>` route, clicking
        # the old pluralised path was a silent dead-end). We also
        # carry `insight=<widget_id>` when the comment is anchored to
        # a widget so the dashboard page's Phase-3.4 scroll-to-widget
        # handler highlights the right one on arrival.
        page_id = comment_data.page_id
        widget_id = comment_data.widget_id
        deep_link = f"/dashboard?id={page_id}"
        if widget_id:
            deep_link += f"&insight={widget_id}"
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
                        deep_link=deep_link,
                    )
                )

        # 2. Notify dashboard owner logic (simplified/omitted for now until owner fetch is robust)

        return db_comment

    async def get_by_page(self, page_id: UUID) -> List[Comment]:
        """Get comments for a page."""
        query = (
            select(Comment)
            .where(Comment.page_id == page_id)
            .order_by(desc(Comment.created_at))
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
