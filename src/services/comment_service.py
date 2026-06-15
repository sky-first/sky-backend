"""Comment service."""

from typing import List
from uuid import UUID

from sqlalchemy import desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from src.core.locale import get_message, normalize_locale
from src.models.comment import Comment
from src.models.notification import NotificationType
from src.models.user import User
from src.schemas.comment import CommentCreate, CommentResponse
from src.schemas.notification import NotificationCreate
from src.services.notification_service import NotificationService

try:
    from src.api.v1.chat_ws import broadcast_event_nowait
except Exception:  # pragma: no cover
    def broadcast_event_nowait(*args, **kwargs):
        return None


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

        broadcast_event_nowait(
            str(db_comment.page_id),
            "comment.created",
            CommentResponse.model_validate(db_comment).model_dump(mode="json"),
        )

        # Trigger Notifications
        # 1. Notify mentioned users
        #
        page_id = comment_data.page_id
        widget_id = comment_data.widget_id
        deep_link = f"/page?id={page_id}"
        if widget_id:
            deep_link += f"&insight={widget_id}"
        recipient_ids = [m for m in comment_data.mentions if m != user_id]
        if recipient_ids:
            # Localize each notification in the recipient's own language —
            # resolve from their stored preferences, not the author's.
            rows = await self.db.execute(
                select(User.id, User.preferences).where(User.id.in_(recipient_ids))
            )
            prefs_by_id = {rid: prefs for rid, prefs in rows.all()}
            snippet = comment_data.content[:50]
            for mentioned_user_id in recipient_ids:
                prefs = prefs_by_id.get(mentioned_user_id) or {}
                locale = normalize_locale(
                    prefs.get("language") if isinstance(prefs, dict) else None
                )
                await self.notification_service.create(
                    NotificationCreate(
                        user_id=mentioned_user_id,
                        type=NotificationType.COMMENT_MENTION,
                        title=get_message("notif_comment_mention_title", locale),
                        description=get_message(
                            "notif_comment_mention_desc", locale
                        ).format(snippet=snippet),
                        entity_type="comment",
                        entity_id=str(db_comment.id),
                        deep_link=deep_link,
                        title_key="notif_comment_mention_title",
                        description_key="notif_comment_mention_desc",
                        description_params={"snippet": snippet},
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
