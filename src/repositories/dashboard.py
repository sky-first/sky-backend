"""Dashboard and widget repositories."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.dashboard import Connection, Dashboard, Widget, WidgetFeedback
from src.repositories.base import BaseRepository


class DashboardRepository(BaseRepository[Dashboard]):
    """Dashboard repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Dashboard)

    async def get_by_page(
        self, page_id: UUID, skip: int = 0, limit: int = 100
    ) -> List[Dashboard]:
        """
        Get dashboards by page.

        Args:
            page_id: Page ID
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List[Dashboard]: List of dashboards
        """
        result = await self.db.execute(
            select(Dashboard)
            .where(Dashboard.page_id == page_id, Dashboard.deleted_at.is_(None))
            .order_by(Dashboard.created_at.desc())
            .offset(skip)
            .limit(limit)
            .options(selectinload(Dashboard.widgets), selectinload(Dashboard.connections))
        )
        return list(result.scalars().all())

    async def get_with_widgets(self, dashboard_id: UUID) -> Optional[Dashboard]:
        """
        Get dashboard with widgets and connections loaded.

        Args:
            dashboard_id: Dashboard ID

        Returns:
            Optional[Dashboard]: Dashboard or None
        """
        result = await self.db.execute(
            select(Dashboard)
            .where(Dashboard.id == dashboard_id, Dashboard.deleted_at.is_(None))
            .options(
                selectinload(Dashboard.widgets),
                selectinload(Dashboard.connections),
            )
        )
        return result.scalar_one_or_none()


class WidgetRepository(BaseRepository[Widget]):
    """Widget repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Widget)

    async def get_by_dashboard(
        self, dashboard_id: UUID, skip: int = 0, limit: int = 100
    ) -> List[Widget]:
        """
        Get widgets by dashboard.

        Ordered by `z_index ASC, created_at ASC` so the canvas renders
        back-to-front and "bring to front" / "send to back" actions are
        reflected by the stored z_index value.
        """
        result = await self.db.execute(
            select(Widget)
            .where(Widget.dashboard_id == dashboard_id)
            .order_by(Widget.z_index.asc(), Widget.created_at.asc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())


class ConnectionRepository(BaseRepository[Connection]):
    """Widget connection repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Connection)

    async def get_by_dashboard(self, dashboard_id: UUID) -> List[Connection]:
        """
        Get connections by dashboard.

        Args:
            dashboard_id: Dashboard ID

        Returns:
            List[Connection]: List of connections
        """
        result = await self.db.execute(
            select(Connection)
            .where(Connection.dashboard_id == dashboard_id)
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
        """
        Get feedback by widget and user.

        Args:
            widget_id: Widget ID
            user_id: User ID

        Returns:
            Optional[WidgetFeedback]: Feedback or None
        """
        result = await self.db.execute(
            select(WidgetFeedback).where(
                WidgetFeedback.widget_id == widget_id, WidgetFeedback.user_id == user_id
            )
        )
        return result.scalar_one_or_none()
