"""Template repository."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.template import Template
from src.repositories.base import BaseRepository


class TemplateRepository(BaseRepository[Template]):
    """Template repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Template)

    async def get_by_category(
        self, category: Optional[str] = None, skip: int = 0, limit: int = 100
    ) -> List[Template]:
        """
        Get templates by category.

        Args:
            category: Optional category filter
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List[Template]: List of templates
        """
        query = select(Template)

        if category:
            query = query.where(Template.category == category)

        query = query.order_by(Template.created_at.desc()).offset(skip).limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def search_templates(
        self, search: str, skip: int = 0, limit: int = 100
    ) -> List[Template]:
        """
        Search templates by name or description.

        Args:
            search: Search query
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List[Template]: List of templates
        """
        query = select(Template).where(
            Template.name.ilike(f"%{search}%") | Template.description.ilike(f"%{search}%")
        )

        query = query.order_by(Template.created_at.desc()).offset(skip).limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_popular(self, skip: int = 0, limit: int = 100) -> List[Template]:
        """
        Get popular templates.

        Args:
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List[Template]: List of templates
        """
        query = select(Template).where(Template.popular == True)

        query = query.order_by(Template.created_at.desc()).offset(skip).limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_categories(self) -> List[str]:
        """
        Get all unique categories.

        Returns:
            List[str]: List of categories
        """
        from sqlalchemy import distinct

        result = await self.db.execute(select(distinct(Template.category)))
        return [row[0] for row in result.all() if row[0]]
