"""Widget service.

Replaces the old ``DashboardService`` (2026-05-20 consolidation). The
dashboard concept was folded into Page; all dashboard CRUD lives on
PageService now. This service owns widget mutations + their feedback.
"""

from datetime import datetime, timezone
from typing import List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError
from src.models.user import User
from src.repositories.page import PageRepository
from src.repositories.widget import (
    ConnectionRepository,
    WidgetFeedbackRepository,
    WidgetRepository,
)
from src.schemas.widget import (
    ConnectionResponse,
    PageExportResponse,
    WidgetCreate,
    WidgetFeedbackCreate,
    WidgetFeedbackResponse,
    WidgetResponse,
    WidgetUpdate,
)
from src.schemas.page import PageResponse


class WidgetService:
    """Widget service — CRUD + feedback for widgets pinned to a Page."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.page_repo = PageRepository(db)
        self.widget_repo = WidgetRepository(db)
        self.connection_repo = ConnectionRepository(db)
        self.feedback_repo = WidgetFeedbackRepository(db)

    # ─── Widget CRUD ───────────────────────────────────────────────────────

    async def create_widget(self, user: User, widget_data: WidgetCreate) -> WidgetResponse:
        """Create a widget on the given page."""
        page = await self.page_repo.get_by_id(widget_data.page_id)
        if not page or page.deleted_at:
            raise NotFoundError("Page not found")

        widget = await self.widget_repo.create(
            page_id=widget_data.page_id,
            type=widget_data.type,
            title=widget_data.title,
            position=widget_data.position,
            size=widget_data.size,
            data=widget_data.data,
            config=widget_data.config,
            connection_id=widget_data.connection_id,
            query_id=widget_data.query_id,
            # Provenance default: 'manual' when the FE didn't stamp it.
            source=widget_data.source or "manual",
            # Stamp the creator so the mutation guard's creator-bypass
            # (src/services/_mutation_guard.py) lets the same user
            # edit/delete the widget they just made.
            created_by=user.id,
        )

        await self.db.commit()
        await self.db.refresh(widget)

        # Ingest the widget into the RAG. Scope (space/crew/owner) inferred
        # from the parent page. Best effort — failures swallowed.
        try:
            from src.ai.http_client import AIServiceHTTPClient
            ai_client = AIServiceHTTPClient()
            space_id = str(page.space_id) if page.space_id else None
            crew_id = str(page.crew_id) if page.crew_id else None
            owner_user_id = str(page.owner_id) if page.type == "personal" else None
            await ai_client.ingest_knowledge_graph({
                "id": str(widget.id),
                "entity_type": "widget",
                "name": widget.title or widget.type,
                "description": f"{widget.type} widget",
                "space_id": space_id,
                "crew_id": crew_id,
                "owner_user_id": owner_user_id,
                "entity_details": {
                    "type": widget.type,
                    "page_id": str(widget.page_id),
                    "connection_id": str(widget.connection_id) if widget.connection_id else None,
                },
            })
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                f"AI ingest failed for widget {widget.id}: {exc}"
            )

        return WidgetResponse.model_validate(widget)

    async def get_widget(self, widget_id: UUID, user: User) -> WidgetResponse:
        widget = await self.widget_repo.get_by_id(widget_id)
        if not widget:
            raise NotFoundError("Widget not found")
        return WidgetResponse.model_validate(widget)

    async def get_page_widgets(self, page_id: UUID, user: User) -> List[WidgetResponse]:
        widgets = await self.widget_repo.get_by_page(page_id)
        return [WidgetResponse.model_validate(w) for w in widgets]

    async def update_widget(
        self, widget_id: UUID, user: User, widget_data: WidgetUpdate
    ) -> WidgetResponse:
        widget = await self.widget_repo.get_by_id(widget_id)
        if not widget:
            raise NotFoundError("Widget not found")

        from src.services._mutation_guard import require_mutation_rights
        await require_mutation_rights(
            widget, user=user, rbac_permission="widgets.edit", db=self.db
        )

        update_data = widget_data.model_dump(exclude_unset=True)
        widget = await self.widget_repo.update(widget_id, **update_data)
        await self.db.commit()
        await self.db.refresh(widget)
        return WidgetResponse.model_validate(widget)

    async def delete_widget(self, widget_id: UUID, user: User) -> None:
        widget = await self.widget_repo.get_by_id(widget_id)
        if not widget:
            raise NotFoundError("Widget not found")

        from src.services._mutation_guard import require_mutation_rights
        await require_mutation_rights(
            widget, user=user, rbac_permission="widgets.delete", db=self.db
        )

        await self.widget_repo.delete(widget_id)
        await self.db.commit()

    async def duplicate_widget(self, widget_id: UUID, user: User) -> WidgetResponse:
        widget = await self.widget_repo.get_by_id(widget_id)
        if not widget:
            raise NotFoundError("Widget not found")

        new_widget = await self.widget_repo.create(
            page_id=widget.page_id,
            type=widget.type,
            title=f"{widget.title} (Copy)",
            position=widget.position.copy() if widget.position else {"x": 0, "y": 0},
            size=widget.size.copy() if widget.size else {"width": 400, "height": 300},
            data=widget.data.copy() if widget.data else None,
            config=widget.config.copy() if widget.config else None,
            connection_id=widget.connection_id,
            query_id=widget.query_id,
            created_by=user.id,
        )
        await self.db.commit()
        await self.db.refresh(new_widget)
        return WidgetResponse.model_validate(new_widget)

    async def export_widget(self, widget_id: UUID, user: User) -> dict:
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
        widget = await self.widget_repo.get_by_id(widget_id)
        if not widget:
            raise NotFoundError("Widget not found")
        return {
            "data": widget.data or {},
            "last_updated": widget.updated_at.isoformat() if widget.updated_at else None,
        }

    async def refresh_widget_data(self, widget_id: UUID, user: User) -> dict:
        widget = await self.widget_repo.get_by_id(widget_id)
        if not widget:
            raise NotFoundError("Widget not found")
        widget.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(widget)
        return {
            "data": widget.data or {},
            "last_updated": widget.updated_at.isoformat() if widget.updated_at else None,
        }

    # ─── Page-level operations that produce widget collections ─────────────

    async def export_page(self, page_id: UUID, user: User) -> PageExportResponse:
        """Export a page with all widgets + connections."""
        page = await self.page_repo.get_by_id(page_id)
        if not page or page.deleted_at:
            raise NotFoundError("Page not found")

        widgets = await self.widget_repo.get_by_page(page_id)
        widget_responses = [WidgetResponse.model_validate(w) for w in widgets]

        connections = await self.connection_repo.get_by_page(page_id)
        connection_responses = [ConnectionResponse.model_validate(c) for c in connections]

        return PageExportResponse(
            page=PageResponse.model_validate(page),
            widgets=widget_responses,
            connections=connection_responses,
            exported_at=datetime.now(timezone.utc).isoformat(),
        )

    # ─── Feedback ──────────────────────────────────────────────────────────

    async def add_widget_feedback(
        self, widget_id: UUID, user: User, feedback_data: WidgetFeedbackCreate
    ) -> WidgetFeedbackResponse:
        widget = await self.widget_repo.get_by_id(widget_id)
        if not widget:
            raise NotFoundError("Widget not found")

        existing_feedback = await self.feedback_repo.get_by_widget_and_user(widget_id, user.id)
        if existing_feedback:
            existing_feedback.score = feedback_data.score
            existing_feedback.reason = feedback_data.reason
            existing_feedback.context = feedback_data.context
            await self.db.commit()
            await self.db.refresh(existing_feedback)
            return WidgetFeedbackResponse.model_validate(existing_feedback)
        else:
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
