"""Page repository."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.crew import CrewMember
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
        Get all pages user has access to.

        Access rules (matching the 4-level model):
          1. Personal pages: owner_id = user (crew_id IS NULL)
          2. Explicit member: user is in page_members for this page
          3. Crew collaborative: page.crew_id is set AND user is a member
             of that crew (via crew_members table)

        Args:
            user_id: User ID

        Returns:
            List[Page]: List of pages (deduplicated, ordered by most recent)
        """
        # Sub-query: crew IDs the user is a member of
        user_crew_ids = (
            select(CrewMember.crew_id).where(CrewMember.user_id == user_id)
        ).scalar_subquery()

        result = await self.db.execute(
            select(Page)
            .outerjoin(PageMember, PageMember.page_id == Page.id)
            .where(
                Page.deleted_at.is_(None),
                or_(
                    # Rule 1: personal pages owned by the user
                    Page.owner_id == user_id,
                    # Rule 2: user is an explicit page member
                    PageMember.user_id == user_id,
                    # Rule 3: collaborative page in a crew the user belongs to
                    Page.crew_id.in_(user_crew_ids),
                ),
            )
            .order_by(Page.updated_at.desc())
        )
        # Deduplicate (a page can match multiple OR branches)
        seen: dict = {}
        for page in result.scalars().all():
            if page.id not in seen:
                seen[page.id] = page
        return list(seen.values())


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
