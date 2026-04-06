"""Page repository."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.page import Page, PageMember
from src.repositories.base import BaseRepository


class PageRepository(BaseRepository[Page]):
    """Page repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Page)

    async def get_by_owner(self, owner_id: UUID, skip: int = 0, limit: int = 100) -> List[Page]:
        """
        Get pages by owner.

        Args:
            owner_id: Owner user ID
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List[Page]: List of pages
        """
        result = await self.db.execute(
            select(Page)
            .where(Page.owner_id == owner_id, Page.deleted_at.is_(None))
            .order_by(Page.last_accessed.desc().nulls_last(), Page.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_active_page(self, user_id: UUID) -> Optional[Page]:
        """
        Get active page for user.

        Args:
            user_id: User ID

        Returns:
            Optional[Page]: Active page or None
        """
        # First try to find page where user is owner and is_active = True
        result = await self.db.execute(
            select(Page)
            .where(
                Page.owner_id == user_id,
                Page.is_active == True,  # noqa: E712
                Page.deleted_at.is_(None),
            )
            .options(selectinload(Page.members), selectinload(Page.dashboards))
        )
        page = result.scalar_one_or_none()

        if page:
            return page

        # If no active page, get the most recently accessed
        result = await self.db.execute(
            select(Page)
            .where(Page.owner_id == user_id, Page.deleted_at.is_(None))
            .order_by(Page.last_accessed.desc().nulls_last(), Page.created_at.desc())
            .limit(1)
            .options(selectinload(Page.members), selectinload(Page.dashboards))
        )
        return result.scalar_one_or_none()

    async def get_user_pages(self, user_id: UUID) -> List[Page]:
        """
        Get all pages user has access to (as owner or member).

        Args:
            user_id: User ID

        Returns:
            List[Page]: List of pages
        """
        # Pages where user is owner
        owned_result = await self.db.execute(
            select(Page).where(Page.owner_id == user_id, Page.deleted_at.is_(None))
        )
        owned = list(owned_result.scalars().all())

        # Pages where user is member
        member_result = await self.db.execute(
            select(Page)
            .join(PageMember)
            .where(
                PageMember.user_id == user_id,
                Page.deleted_at.is_(None),
            )
        )
        member_pages = list(member_result.scalars().all())

        # Combine and deduplicate
        all_pages = {p.id: p for p in owned + member_pages}
        return list(all_pages.values())


class PageMemberRepository(BaseRepository[PageMember]):
    """Page member repository."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, PageMember)

    async def get_by_page_and_user(
        self, page_id: UUID, user_id: UUID
    ) -> Optional[PageMember]:
        """
        Get page member by page and user.

        Args:
            page_id: Page ID
            user_id: User ID

        Returns:
            Optional[PageMember]: Member or None
        """
        result = await self.db.execute(
            select(PageMember).where(
                PageMember.page_id == page_id,
                PageMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_page_members(self, page_id: UUID) -> List[PageMember]:
        """
        Get all members of a page.

        Args:
            page_id: Page ID

        Returns:
            List[PageMember]: List of members
        """
        result = await self.db.execute(
            select(PageMember)
            .where(PageMember.page_id == page_id)
            .options(selectinload(PageMember.user))
        )
        return list(result.scalars().all())
