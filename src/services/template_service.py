"""Template service."""

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError, NotFoundError
from src.core.permissions import check_permission
from src.models.user import User
from src.repositories.dashboard import DashboardRepository, WidgetRepository
from src.repositories.template import TemplateRepository
from src.schemas.dashboard import WidgetCreate, WidgetResponse
from src.schemas.template import (
    TemplateApplyRequest,
    TemplateApplyResponse,
    TemplateCreate,
    TemplateResponse,
    TemplateUpdate,
)


class TemplateService:
    """Template service."""

    def __init__(self, db: AsyncSession):
        """
        Initialize template service.

        Args:
            db: Database session
        """
        self.db = db
        self.template_repo = TemplateRepository(db)
        self.dashboard_repo = DashboardRepository(db)
        self.widget_repo = WidgetRepository(db)

    async def list_templates(
        self,
        user: User,
        category: Optional[str] = None,
        search: Optional[str] = None,
        popular: Optional[bool] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[TemplateResponse]:
        """
        List templates.

        Args:
            user: Current user
            category: Optional category filter
            search: Optional search query
            popular: Optional popular filter
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List[TemplateResponse]: List of templates
        """
        if search:
            templates = await self.template_repo.search_templates(search, skip=skip, limit=limit)
        elif popular:
            templates = await self.template_repo.get_popular(skip=skip, limit=limit)
        elif category:
            templates = await self.template_repo.get_by_category(category, skip=skip, limit=limit)
        else:
            templates = await self.template_repo.get_all(skip=skip, limit=limit)

        return [TemplateResponse.model_validate(t) for t in templates]

    async def get_template(self, template_id: UUID, user: User) -> TemplateResponse:
        """
        Get template by ID.

        Args:
            template_id: Template ID
            user: Current user

        Returns:
            TemplateResponse: Template data

        Raises:
            NotFoundError: If template not found
        """
        template = await self.template_repo.get_by_id(template_id)
        if not template:
            raise NotFoundError("Template not found")

        return TemplateResponse.model_validate(template)

    async def create_template(self, user: User, template_data: TemplateCreate) -> TemplateResponse:
        """
        Create a new template.

        Args:
            user: Current user
            template_data: Template creation data

        Returns:
            TemplateResponse: Created template

        Raises:
            ForbiddenError: If user doesn't have permission
        """
        # Only admins can create templates
        if not check_permission(user, "template", "create"):
            raise ForbiddenError("Only administrators can create templates")

        template = await self.template_repo.create(**template_data.model_dump())
        await self.db.commit()
        await self.db.refresh(template)

        return TemplateResponse.model_validate(template)

    async def update_template(
        self, template_id: UUID, user: User, template_data: TemplateUpdate
    ) -> TemplateResponse:
        """
        Update template.

        Args:
            template_id: Template ID
            user: Current user
            template_data: Template update data

        Returns:
            TemplateResponse: Updated template

        Raises:
            NotFoundError: If template not found
            ForbiddenError: If user doesn't have permission
        """
        template = await self.template_repo.get_by_id(template_id)
        if not template:
            raise NotFoundError("Template not found")

        # Only admins can update templates
        if not check_permission(user, "template", "update"):
            raise ForbiddenError("Only administrators can update templates")

        update_data = template_data.model_dump(exclude_unset=True)
        template = await self.template_repo.update(template_id, **update_data)
        await self.db.commit()
        await self.db.refresh(template)

        return TemplateResponse.model_validate(template)

    async def delete_template(self, template_id: UUID, user: User) -> None:
        """
        Delete template.

        Args:
            template_id: Template ID
            user: Current user

        Raises:
            NotFoundError: If template not found
            ForbiddenError: If user doesn't have permission
        """
        template = await self.template_repo.get_by_id(template_id)
        if not template:
            raise NotFoundError("Template not found")

        # Only admins can delete templates
        if not check_permission(user, "template", "delete"):
            raise ForbiddenError("Only administrators can delete templates")

        await self.template_repo.delete(template_id)
        await self.db.commit()

    async def get_categories(self, user: User) -> List[str]:
        """
        Get all template categories.

        Args:
            user: Current user

        Returns:
            List[str]: List of categories
        """
        categories = await self.template_repo.get_categories()
        return categories

    async def apply_template(
        self, template_id: UUID, user: User, apply_data: TemplateApplyRequest
    ) -> TemplateApplyResponse:
        """
        Apply template to a dashboard.

        Args:
            template_id: Template ID
            user: Current user
            apply_data: Template apply data

        Returns:
            TemplateApplyResponse: Created widgets

        Raises:
            NotFoundError: If template or dashboard not found
            ForbiddenError: If user doesn't have access
        """
        template = await self.template_repo.get_by_id(template_id)
        if not template:
            raise NotFoundError("Template not found")

        dashboard = await self.dashboard_repo.get_by_id(apply_data.dashboard_id)
        if not dashboard or dashboard.deleted_at:
            raise NotFoundError("Dashboard not found")

        # TODO: Check workspace access

        # Create widgets from template
        created_widgets = []
        base_position = apply_data.position or {"x": 0, "y": 0}

        for idx, widget_def in enumerate(template.widgets):
            # Calculate position (offset widgets)
            position = {
                "x": base_position.get("x", 0) + (idx % 3) * 450,
                "y": base_position.get("y", 0) + (idx // 3) * 350,
            }

            widget = await self.widget_repo.create(
                dashboard_id=apply_data.dashboard_id,
                type=widget_def.get("type", "chart"),
                title=widget_def.get("title", "Widget"),
                position=position,
                size=widget_def.get("size", {"width": 400, "height": 300}),
                data=widget_def.get("data"),
                config=widget_def.get("config"),
                connection_id=widget_def.get("connection_id"),
                query_id=widget_def.get("query_id"),
            )
            created_widgets.append(WidgetResponse.model_validate(widget).model_dump())

        await self.db.commit()

        return TemplateApplyResponse(widgets=created_widgets)
