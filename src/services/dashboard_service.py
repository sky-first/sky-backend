"""Dashboard service."""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError, NotFoundError
from src.models.user import User
from src.repositories.dashboard import (
    ConnectionRepository,
    DashboardRepository,
    WidgetFeedbackRepository,
    WidgetRepository,
)
from src.schemas.dashboard import (
    ConnectionResponse,
    DashboardCreate,
    DashboardDuplicateRequest,
    DashboardExportResponse,
    DashboardResponse,
    DashboardUpdate,
    WidgetCreate,
    WidgetFeedbackCreate,
    WidgetFeedbackResponse,
    WidgetResponse,
    WidgetUpdate,
)
from src.models.notification import NotificationType
from src.schemas.notification import NotificationCreate
from src.services.notification_service import NotificationService


class DashboardService:
    """Dashboard service."""

    def __init__(self, db: AsyncSession):
        """
        Initialize dashboard service.

        Args:
            db: Database session
        """
        self.db = db
        self.dashboard_repo = DashboardRepository(db)
        self.widget_repo = WidgetRepository(db)
        self.connection_repo = ConnectionRepository(db)
        self.feedback_repo = WidgetFeedbackRepository(db)
        self.notification_service = NotificationService(db)

    async def create_dashboard(
        self, user: User, dashboard_data: DashboardCreate
    ) -> DashboardResponse:
        """
        Create a new dashboard.

        Args:
            user: Current user
            dashboard_data: Dashboard creation data

        Returns:
            DashboardResponse: Created dashboard

        Raises:
            NotFoundError: If planet not found
            ForbiddenError: If user doesn't have access to planet
        """
        # Verify planet exists and user has access
        from src.repositories.planet import PlanetRepository

        planet_repo = PlanetRepository(self.db)
        planet = await planet_repo.get_by_id(dashboard_data.planet_id)

        if not planet or planet.deleted_at:
            raise NotFoundError(f"Planet with id {dashboard_data.planet_id} not found")

        # Check if user has access to this planet
        if planet.owner_id != user.id:
            from src.repositories.planet import PlanetMemberRepository

            member_repo = PlanetMemberRepository(self.db)
            member = await member_repo.get_by_planet_and_user(dashboard_data.planet_id, user.id)
            if not member:
                raise ForbiddenError("Access denied to this planet")

        dashboard = await self.dashboard_repo.create(
            name=dashboard_data.name,
            description=dashboard_data.description,
            planet_id=dashboard_data.planet_id,
            template_id=dashboard_data.template_id,
            created_by=user.id,
            canvas_settings={
                "scale": 1,
                "position": {"x": 0, "y": 0},
                "snapToGrid": False,
                "gridSize": 24,
            },
            is_locked=False,
        )

        await self.db.commit()
        await self.db.refresh(dashboard)

        return DashboardResponse.model_validate(dashboard)

    async def get_dashboard(self, dashboard_id: UUID, user: User) -> DashboardResponse:
        """
        Get dashboard by ID.

        Args:
            dashboard_id: Dashboard ID
            user: Current user

        Returns:
            DashboardResponse: Dashboard data

        Raises:
            NotFoundError: If dashboard not found
        """
        dashboard = await self.dashboard_repo.get_with_widgets(dashboard_id)
        if not dashboard or dashboard.deleted_at:
            raise NotFoundError("Dashboard not found")

        # TODO: Check planet access

        return DashboardResponse.model_validate(dashboard)

    async def get_planet_dashboards(
        self, planet_id: UUID, user: User, skip: int = 0, limit: int = 100
    ) -> List[DashboardResponse]:
        """
        Get dashboards by planet.

        Args:
            planet_id: Planet ID
            user: Current user
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List[DashboardResponse]: List of dashboards
        """
        dashboards = await self.dashboard_repo.get_by_planet(planet_id, skip=skip, limit=limit)
        return [DashboardResponse.model_validate(d) for d in dashboards]

    async def update_dashboard(
        self, dashboard_id: UUID, user: User, dashboard_data: DashboardUpdate
    ) -> DashboardResponse:
        """
        Update dashboard.

        Args:
            dashboard_id: Dashboard ID
            user: Current user
            dashboard_data: Dashboard update data

        Returns:
            DashboardResponse: Updated dashboard

        Raises:
            NotFoundError: If dashboard not found
        """
        dashboard = await self.dashboard_repo.get_by_id(dashboard_id)
        if not dashboard or dashboard.deleted_at:
            raise NotFoundError("Dashboard not found")

        # TODO: Check workspace access

        update_data = dashboard_data.model_dump(exclude_unset=True)
        dashboard = await self.dashboard_repo.update(dashboard_id, **update_data)
        await self.db.commit()
        await self.db.refresh(dashboard)

        # Trigger Notification if updated by another user
        if dashboard.created_by and dashboard.created_by != user.id:
            try:
                await self.notification_service.create(
                    NotificationCreate(
                        user_id=dashboard.created_by,
                        space_id=None,  # Optimization: fetch space/planet if needed
                        type=NotificationType.DASHBOARD_EDITED_BY_OTHER,
                        title="Dashboard Edited",
                        description=f"User {user.email or user.id} edited your dashboard '{dashboard.name}'",
                        entity_type="dashboard",
                        entity_id=dashboard.id,
                        deep_link=f"/dashboards/{dashboard.id}",
                    )
                )
            except Exception:
                # Fail silently to not block the main action
                pass

        return DashboardResponse.model_validate(dashboard)

    async def delete_dashboard(self, dashboard_id: UUID, user: User) -> None:
        """
        Delete dashboard.

        Args:
            dashboard_id: Dashboard ID
            user: Current user

        Raises:
            NotFoundError: If dashboard not found
        """
        dashboard = await self.dashboard_repo.get_by_id(dashboard_id)
        if not dashboard or dashboard.deleted_at:
            raise NotFoundError("Dashboard not found")

        # TODO: Check workspace access

        await self.dashboard_repo.delete(dashboard_id)
        await self.db.commit()

    async def create_widget(self, user: User, widget_data: WidgetCreate) -> WidgetResponse:
        """
        Create a new widget.

        Args:
            user: Current user
            widget_data: Widget creation data

        Returns:
            WidgetResponse: Created widget

        Raises:
            NotFoundError: If dashboard not found
        """
        # Verify dashboard exists
        dashboard = await self.dashboard_repo.get_by_id(widget_data.dashboard_id)
        if not dashboard or dashboard.deleted_at:
            raise NotFoundError("Dashboard not found")

        widget = await self.widget_repo.create(
            dashboard_id=widget_data.dashboard_id,
            type=widget_data.type,
            title=widget_data.title,
            position=widget_data.position,
            size=widget_data.size,
            data=widget_data.data,
            config=widget_data.config,
            connection_id=widget_data.connection_id,
            query_id=widget_data.query_id,
        )

        await self.db.commit()
        await self.db.refresh(widget)

        return WidgetResponse.model_validate(widget)

    async def get_widget(self, widget_id: UUID, user: User) -> WidgetResponse:
        """
        Get widget by ID.

        Args:
            widget_id: Widget ID
            user: Current user

        Returns:
            WidgetResponse: Widget data

        Raises:
            NotFoundError: If widget not found
        """
        widget = await self.widget_repo.get_by_id(widget_id)
        if not widget:
            raise NotFoundError("Widget not found")

        return WidgetResponse.model_validate(widget)

    async def get_dashboard_widgets(self, dashboard_id: UUID, user: User) -> List[WidgetResponse]:
        """
        Get widgets by dashboard.

        Args:
            dashboard_id: Dashboard ID
            user: Current user

        Returns:
            List[WidgetResponse]: List of widgets
        """
        widgets = await self.widget_repo.get_by_dashboard(dashboard_id)
        return [WidgetResponse.model_validate(w) for w in widgets]

    async def update_widget(
        self, widget_id: UUID, user: User, widget_data: WidgetUpdate
    ) -> WidgetResponse:
        """
        Update widget.

        Args:
            widget_id: Widget ID
            user: Current user
            widget_data: Widget update data

        Returns:
            WidgetResponse: Updated widget

        Raises:
            NotFoundError: If widget not found
            ForbiddenError: If user doesn't have access to the dashboard
        """
        widget = await self.widget_repo.get_by_id(widget_id)
        if not widget:
            raise NotFoundError("Widget not found")

        # Verify user has access to the dashboard
        await self.get_dashboard(widget.dashboard_id, user)

        update_data = widget_data.model_dump(exclude_unset=True)
        widget = await self.widget_repo.update(widget_id, **update_data)
        await self.db.commit()
        await self.db.refresh(widget)

        return WidgetResponse.model_validate(widget)

    async def delete_widget(self, widget_id: UUID, user: User) -> None:
        """
        Delete widget.

        Args:
            widget_id: Widget ID
            user: Current user

        Raises:
            NotFoundError: If widget not found
        """
        widget = await self.widget_repo.get_by_id(widget_id)
        if not widget:
            raise NotFoundError("Widget not found")

        await self.widget_repo.delete(widget_id)
        await self.db.commit()

    async def list_dashboards(
        self, user: User, planet_id: Optional[UUID] = None, skip: int = 0, limit: int = 100
    ) -> List[DashboardResponse]:
        """
        List dashboards.

        Args:
            user: Current user
            planet_id: Optional planet ID to filter
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List[DashboardResponse]: List of dashboards
        """
        if planet_id:
            dashboards = await self.dashboard_repo.get_by_planet(planet_id, skip=skip, limit=limit)
        else:
            # Get all dashboards user has access to (via planets)
            # For now, return empty list if no planet_id specified
            # TODO: Implement proper planet-based filtering
            dashboards = []

        return [DashboardResponse.model_validate(d) for d in dashboards]

    async def duplicate_widget(self, widget_id: UUID, user: User) -> WidgetResponse:
        """
        Duplicate widget.

        Args:
            widget_id: Widget ID to duplicate
            user: Current user

        Returns:
            WidgetResponse: Duplicated widget

        Raises:
            NotFoundError: If widget not found
        """
        widget = await self.widget_repo.get_by_id(widget_id)
        if not widget:
            raise NotFoundError("Widget not found")

        # Create duplicate with modified title
        new_widget = await self.widget_repo.create(
            dashboard_id=widget.dashboard_id,
            type=widget.type,
            title=f"{widget.title} (Copy)",
            position=widget.position.copy() if widget.position else {"x": 0, "y": 0},
            size=widget.size.copy() if widget.size else {"width": 400, "height": 300},
            data=widget.data.copy() if widget.data else None,
            config=widget.config.copy() if widget.config else None,
            connection_id=widget.connection_id,
            query_id=widget.query_id,
        )

        await self.db.commit()
        await self.db.refresh(new_widget)

        return WidgetResponse.model_validate(new_widget)

    async def export_widget(self, widget_id: UUID, user: User) -> dict:
        """
        Export widget data.

        Args:
            widget_id: Widget ID
            user: Current user

        Returns:
            dict: Widget export data

        Raises:
            NotFoundError: If widget not found
        """
        widget = await self.widget_repo.get_by_id(widget_id)
        if not widget:
            raise NotFoundError("Widget not found")

        return {
            "id": str(widget.id),
            "type": widget.type,
            "title": widget.title,
            "position": widget.position,
            "size": widget.size,
            "data": widget.data,
            "config": widget.config,
            "connection_id": str(widget.connection_id) if widget.connection_id else None,
            "query_id": str(widget.query_id) if widget.query_id else None,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }

    async def get_widget_data(self, widget_id: UUID, user: User) -> dict:
        """
        Get widget data.

        Args:
            widget_id: Widget ID
            user: Current user

        Returns:
            dict: Widget data

        Raises:
            NotFoundError: If widget not found
        """
        widget = await self.widget_repo.get_by_id(widget_id)
        if not widget:
            raise NotFoundError("Widget not found")

        return {
            "data": widget.data or {},
            "last_updated": widget.updated_at.isoformat() if widget.updated_at else None,
        }

    async def refresh_widget_data(self, widget_id: UUID, user: User) -> dict:
        """
        Refresh widget data.

        Args:
            widget_id: Widget ID
            user: Current user

        Returns:
            dict: Refreshed widget data

        Raises:
            NotFoundError: If widget not found
        """
        widget = await self.widget_repo.get_by_id(widget_id)
        if not widget:
            raise NotFoundError("Widget not found")

        # TODO: Implement actual data refresh logic
        # For now, just update the timestamp
        widget.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(widget)

        return {
            "data": widget.data or {},
            "last_updated": widget.updated_at.isoformat() if widget.updated_at else None,
        }

    async def export_dashboard(self, dashboard_id: UUID, user: User) -> DashboardExportResponse:
        """
        Export dashboard with all widgets and connections.

        Args:
            dashboard_id: Dashboard ID
            user: Current user

        Returns:
            DashboardExportResponse: Dashboard export data

        Raises:
            NotFoundError: If dashboard not found
        """
        dashboard = await self.dashboard_repo.get_with_widgets(dashboard_id)
        if not dashboard or dashboard.deleted_at:
            raise NotFoundError("Dashboard not found")

        # Get all widgets
        widgets = await self.widget_repo.get_by_dashboard(dashboard_id)
        widget_responses = [WidgetResponse.model_validate(w) for w in widgets]

        # Get all connections
        connections = await self.connection_repo.get_by_dashboard(dashboard_id)
        connection_responses = [ConnectionResponse.model_validate(c) for c in connections]

        return DashboardExportResponse(
            dashboard=DashboardResponse.model_validate(dashboard),
            widgets=widget_responses,
            connections=connection_responses,
            exported_at=datetime.now(timezone.utc).isoformat(),
        )

    async def duplicate_dashboard(
        self,
        dashboard_id: UUID,
        user: User,
        duplicate_data: Optional[DashboardDuplicateRequest] = None,
    ) -> DashboardResponse:
        """
        Duplicate dashboard with all widgets.

        Args:
            dashboard_id: Dashboard ID to duplicate
            user: Current user
            duplicate_data: Optional duplicate configuration

        Returns:
            DashboardResponse: Duplicated dashboard

        Raises:
            NotFoundError: If dashboard not found
        """
        # Get original dashboard with widgets
        original_dashboard = await self.dashboard_repo.get_with_widgets(dashboard_id)
        if not original_dashboard or original_dashboard.deleted_at:
            raise NotFoundError("Dashboard not found")

        # Determine new dashboard name
        new_name = (
            duplicate_data.name
            if duplicate_data and duplicate_data.name
            else f"{original_dashboard.name} (Copy)"
        )

        # Determine planet_id
        new_planet_id = (
            duplicate_data.planet_id
            if duplicate_data and duplicate_data.planet_id
            else original_dashboard.planet_id
        )

        # Create new dashboard
        new_dashboard = await self.dashboard_repo.create(
            name=new_name,
            description=original_dashboard.description,
            planet_id=new_planet_id,
            template_id=original_dashboard.template_id,
            created_by=user.id,
            canvas_settings=(
                original_dashboard.canvas_settings.copy()
                if original_dashboard.canvas_settings
                else None
            ),
            is_locked=False,  # New dashboard starts unlocked
        )

        await self.db.commit()
        await self.db.refresh(new_dashboard)

        # Duplicate all widgets
        original_widgets = await self.widget_repo.get_by_dashboard(dashboard_id)
        for original_widget in original_widgets:
            await self.widget_repo.create(
                dashboard_id=new_dashboard.id,
                type=original_widget.type,
                title=original_widget.title,
                position=(
                    original_widget.position.copy()
                    if original_widget.position
                    else {"x": 0, "y": 0}
                ),
                size=(
                    original_widget.size.copy()
                    if original_widget.size
                    else {"width": 400, "height": 300}
                ),
                data=original_widget.data.copy() if original_widget.data else None,
                config=original_widget.config.copy() if original_widget.config else None,
                connection_id=original_widget.connection_id,
                query_id=original_widget.query_id,
            )

        await self.db.commit()
        await self.db.refresh(new_dashboard)

        return DashboardResponse.model_validate(new_dashboard)

    async def lock_dashboard(self, dashboard_id: UUID, user: User) -> DashboardResponse:
        """
        Lock dashboard.

        Args:
            dashboard_id: Dashboard ID
            user: Current user

        Returns:
            DashboardResponse: Locked dashboard

        Raises:
            NotFoundError: If dashboard not found
        """
        dashboard = await self.dashboard_repo.get_by_id(dashboard_id)
        if not dashboard or dashboard.deleted_at:
            raise NotFoundError("Dashboard not found")

        # TODO: Check planet access

        dashboard = await self.dashboard_repo.update(dashboard_id, is_locked=True)
        await self.db.commit()
        await self.db.refresh(dashboard)

        return DashboardResponse.model_validate(dashboard)

    async def unlock_dashboard(self, dashboard_id: UUID, user: User) -> DashboardResponse:
        """
        Unlock dashboard.

        Args:
            dashboard_id: Dashboard ID
            user: Current user

        Returns:
            DashboardResponse: Unlocked dashboard

        Raises:
            NotFoundError: If dashboard not found
        """
        dashboard = await self.dashboard_repo.get_by_id(dashboard_id)
        if not dashboard or dashboard.deleted_at:
            raise NotFoundError("Dashboard not found")

        # TODO: Check planet access

        dashboard = await self.dashboard_repo.update(dashboard_id, is_locked=False)
        await self.db.commit()
        await self.db.refresh(dashboard)

        return DashboardResponse.model_validate(dashboard)

    async def add_widget_feedback(
        self, widget_id: UUID, user: User, feedback_data: WidgetFeedbackCreate
    ) -> WidgetFeedbackResponse:
        """
        Add feedback to widget.

        Args:
            widget_id: Widget ID
            user: Current user
            feedback_data: Feedback data

        Returns:
            WidgetFeedbackResponse: Created/Updated feedback

        Raises:
            NotFoundError: If widget not found
        """
        widget = await self.widget_repo.get_by_id(widget_id)
        if not widget:
            raise NotFoundError("Widget not found")

        # Check if user already voted
        existing_feedback = await self.feedback_repo.get_by_widget_and_user(widget_id, user.id)

        if existing_feedback:
            # Update existing feedback
            existing_feedback.score = feedback_data.score
            existing_feedback.reason = feedback_data.reason
            existing_feedback.context = feedback_data.context
            await self.db.commit()
            await self.db.refresh(existing_feedback)
            return WidgetFeedbackResponse.model_validate(existing_feedback)
        else:
            # Create new feedback
            feedback = await self.feedback_repo.create(
                widget_id=widget_id,
                user_id=user.id,
                score=feedback_data.score,
                reason=feedback_data.reason,
                context=feedback_data.context,
            )
            await self.db.commit()
            await self.db.refresh(feedback)
            return WidgetFeedbackResponse.model_validate(feedback)
