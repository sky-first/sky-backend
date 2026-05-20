"""Widget, Connection, WidgetFeedback repositories.

Renamed from ``repositories/dashboard.py`` in 2026-05-20. The
``PageRepository`` class was removed — page CRUD lives in
``PageRepository`` now.
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.widget import Connection, Widget, WidgetFeedback
from src.repositories.base import BaseRepository


class WidgetRepository(BaseRepository[Widget]):
    """Widget repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Widget)

    async def get_by_page(
        self, page_id: UUID, skip: int = 0, limit: int = 100
    ) -> List[Widget]:
        """
        Get widgets by page.

        Ordered by ``z_index ASC, created_at ASC`` so the canvas renders
        back-to-front and "bring to front" / "send to back" actions are
        reflected by the stored z_index value.
        """
        result = await self.db.execute(
            select(Widget)
            .where(Widget.page_id == page_id)
            .order_by(Widget.z_index.asc(), Widget.created_at.asc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())


class ConnectionRepository(BaseRepository[Connection]):
    """Widget connection repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Connection)

    async def get_by_page(self, page_id: UUID) -> List[Connection]:
        """Get connections by page."""
        result = await self.db.execute(
            select(Connection)
            .where(Connection.page_id == page_id)
            .options(
                selectinload(Connection.from_widget),
                selectinload(Connection.to_widget),
            )
        )
        return list(result.scalars().all())


class WidgetFeedbackRepository(BaseRepository[WidgetFeedback]):
    """Widget feedback repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, WidgetFeedback)

    async def get_by_widget_and_user(
        self, widget_id: UUID, user_id: UUID
    ) -> Optional[WidgetFeedback]:
        """Get feedback by widget and user."""
        result = await self.db.execute(
            select(WidgetFeedback).where(
                WidgetFeedback.widget_id == widget_id,
                WidgetFeedback.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()
