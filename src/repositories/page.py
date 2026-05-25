"""Page repository."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.crew import CrewMember
from src.models.page import Page, PageMember
from src.models.space import SpaceMember
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
            # Page-consolidation (2026-05-20): Page IS the canvas now,
            # so Page.dashboards collection is gone. Only Page.members
            # remains as a relationship to eager-load.
            .options(selectinload(Page.members))
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
            # Page-consolidation (2026-05-20): Page IS the canvas now,
            # so Page.dashboards collection is gone. Only Page.members
            # remains as a relationship to eager-load.
            .options(selectinload(Page.members))
        )
        return result.scalar_one_or_none()

    async def get_user_pages(
        self,
        user_id: UUID,
        *,
        context: str = "all",
        space_id: Optional[UUID] = None,
        crew_id: Optional[UUID] = None,
    ) -> List[Page]:
        """
        Get pages filtered by navigation context.

        Contexts:
          "personal" → only personal pages (space_id=NULL, crew_id=NULL, owner=me)
          "space"    → space-level pages (space_id=X, crew_id=NULL) + requires space_id
          "crew"     → crew-level pages (crew_id=Y) + requires crew_id
          "all"      → everything the user can access (default, legacy behavior)

        Access rules:
          1. Personal: owner_id = user AND crew_id IS NULL AND space_id IS NULL
          2. Space-level: space_id is set AND user is member of that space
          3. Crew-level: crew_id is set AND user is member of that crew
          4. Explicit page_members
        """
        user_crew_ids = (
            select(CrewMember.crew_id).where(CrewMember.user_id == user_id)
        ).scalar_subquery()

        user_space_ids = (
            select(SpaceMember.space_id).where(SpaceMember.user_id == user_id)
        ).scalar_subquery()

        base = select(Page).outerjoin(PageMember, PageMember.page_id == Page.id).where(
            Page.deleted_at.is_(None)
        )

        if context == "personal":
            base = base.where(
                Page.owner_id == user_id,
                Page.crew_id.is_(None),
                Page.space_id.is_(None),
            )
        elif context == "space" and space_id:
            base = base.where(
                Page.space_id == space_id,
                Page.crew_id.is_(None),
            )
        elif context == "crew" and crew_id:
            base = base.where(Page.crew_id == crew_id)
        else:
            # "all" — everything the user can access
            base = base.where(
                or_(
                    Page.owner_id == user_id,
                    PageMember.user_id == user_id,
                    Page.crew_id.in_(user_crew_ids),
                    Page.space_id.in_(user_space_ids),
                ),
            )

        result = await self.db.execute(base.order_by(Page.updated_at.desc()))
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
