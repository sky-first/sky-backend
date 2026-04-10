"""Page service."""

from datetime import datetime, timezone
from typing import List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ForbiddenError, NotFoundError
from src.models.page import Page
from src.models.user import User
from src.repositories.page import PageMemberRepository, PageRepository
from src.schemas.page import (
    PageCreate,
    PageMemberCreate,
    PageMemberResponse,
    PageResponse,
    PageUpdate,
)


class PageService:
    """Page service."""

    def __init__(self, db: AsyncSession):
        """
        Initialize page service.

        Args:
            db: Database session
        """
        self.db = db
        self.page_repo = PageRepository(db)
        self.member_repo = PageMemberRepository(db)

    async def create_page(self, user: User, page_data: PageCreate) -> PageResponse:
        """
        Create a new page.

        Args:
            user: Current user
            page_data: Page creation data

        Returns:
            PageResponse: Created page
        """
        crew_id = getattr(page_data, "crew_id", None)

        # P0 fix: validate crew membership before creating collaborative page
        if crew_id:
            # Reject personal type with crew_id
            if page_data.type == "personal":
                raise ForbiddenError(
                    "Personal pages cannot be assigned to a crew. "
                    "Use type='team' for collaborative pages."
                )
            # Verify the crew exists and user is a member
            from src.repositories.crew import CrewMemberRepository, CrewRepository

            crew_repo = CrewRepository(self.db)
            crew = await crew_repo.get_by_id(crew_id)
            if not crew:
                raise NotFoundError("Crew not found")
            crew_member_repo = CrewMemberRepository(self.db)
            member = await crew_member_repo.get_by_crew_and_user(crew_id, user.id)
            # Allow if user is admin (admin bypass) or crew member
            if not member and user.role != "admin":
                raise ForbiddenError(
                    "You must be a member of this crew to create collaborative pages"
                )

        page = await self.page_repo.create(
            name=page_data.name,
            description=page_data.description,
            type=page_data.type,
            color=page_data.color,
            icon=page_data.icon,
            owner_id=user.id,
            crew_id=crew_id,
            is_active=False,
        )

        # Add owner as member
        await self.member_repo.create(
            page_id=page.id,
            user_id=user.id,
            role="owner",
        )

        await self.db.commit()
        await self.db.refresh(page)

        return PageResponse.model_validate(page)

    async def get_page(self, page_id: UUID, user: User) -> PageResponse:
        """
        Get page by ID.

        Args:
            page_id: Page ID
            user: Current user

        Returns:
            PageResponse: Page data

        Raises:
            NotFoundError: If page not found
            ForbiddenError: If user doesn't have access
        """
        page = await self.page_repo.get_by_id(page_id)
        if not page or page.deleted_at:
            raise NotFoundError("Page not found")

        # Check access
        if page.owner_id != user.id:
            member = await self.member_repo.get_by_page_and_user(page_id, user.id)
            if not member:
                # Check crew membership for collaborative pages
                if page.crew_id:
                    from src.repositories.crew import CrewMemberRepository

                    crew_member_repo = CrewMemberRepository(self.db)
                    crew_member = await crew_member_repo.get_by_crew_and_user(
                        page.crew_id, user.id
                    )
                    if not crew_member:
                        raise NotFoundError("Page not found")
                else:
                    raise NotFoundError("Page not found")

        return PageResponse.model_validate(page)

    async def get_user_pages(self, user: User) -> List[PageResponse]:
        """
        Get all pages for user.

        Args:
            user: Current user

        Returns:
            List[PageResponse]: List of pages
        """
        pages = await self.page_repo.get_user_pages(user.id)
        return [PageResponse.model_validate(w) for w in pages]

    async def update_page(
        self, page_id: UUID, user: User, page_data: PageUpdate
    ) -> PageResponse:
        """
        Update page.

        Args:
            page_id: Page ID
            user: Current user
            page_data: Page update data

        Returns:
            PageResponse: Updated page

        Raises:
            NotFoundError: If page not found
            ForbiddenError: If user doesn't have permission
        """
        page = await self.page_repo.get_by_id(page_id)
        if not page or page.deleted_at:
            raise NotFoundError("Page not found")

        # Check permission (only owner or admin can update)
        if page.owner_id != user.id:
            member = await self.member_repo.get_by_page_and_user(page_id, user.id)
            if not member or member.role not in ["owner", "admin"]:
                raise ForbiddenError("Permission denied")

        update_data = page_data.model_dump(exclude_unset=True)
        page = await self.page_repo.update(page_id, **update_data)
        await self.db.commit()
        await self.db.refresh(page)

        return PageResponse.model_validate(page)

    async def delete_page(self, page_id: UUID, user: User) -> None:
        """
        Delete page.

        Args:
            page_id: Page ID
            user: Current user

        Raises:
            NotFoundError: If page not found
            ForbiddenError: If user is not owner
        """
        page = await self.page_repo.get_by_id(page_id)
        if not page or page.deleted_at:
            raise NotFoundError("Page not found")

        # Only owner can delete
        if page.owner_id != user.id:
            raise ForbiddenError("Only page owner can delete")

        await self.page_repo.delete(page_id)
        await self.db.commit()

    async def switch_page(self, page_id: UUID, user: User) -> PageResponse:
        """
        Switch active page.

        Args:
            page_id: Page ID to switch to
            user: Current user

        Returns:
            PageResponse: Active page

        Raises:
            NotFoundError: If page not found
            ForbiddenError: If user doesn't have access
        """
        page = await self.page_repo.get_by_id(page_id)
        if not page or page.deleted_at:
            raise NotFoundError("Page not found")

        # Check access
        if page.owner_id != user.id:
            member = await self.member_repo.get_by_page_and_user(page_id, user.id)
            if not member:
                # Check crew membership for collaborative pages
                if page.crew_id:
                    from src.repositories.crew import CrewMemberRepository

                    crew_member_repo = CrewMemberRepository(self.db)
                    crew_member = await crew_member_repo.get_by_crew_and_user(
                        page.crew_id, user.id
                    )
                    if not crew_member:
                        raise NotFoundError("Page not found")
                else:
                    raise NotFoundError("Page not found")

        # Deactivate all other pages for this user
        from sqlalchemy import update

        await self.db.execute(
            update(Page)
            .where(Page.owner_id == user.id, Page.id != page_id)
            .values(is_active=False)
        )

        # Activate this page
        page.is_active = True
        page.last_accessed = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(page)

        return PageResponse.model_validate(page)

    async def add_member(
        self, page_id: UUID, user: User, member_data: PageMemberCreate
    ) -> PageMemberResponse:
        """
        Add member to page.

        Args:
            page_id: Page ID
            user: Current user
            member_data: Member data

        Returns:
            PageMemberResponse: Created member

        Raises:
            NotFoundError: If page not found
            ForbiddenError: If user doesn't have permission
        """
        page = await self.page_repo.get_by_id(page_id)
        if not page or page.deleted_at:
            raise NotFoundError("Page not found")

        # Check permission (only owner or admin can add members)
        if page.owner_id != user.id:
            member = await self.member_repo.get_by_page_and_user(page_id, user.id)
            if not member or member.role not in ["owner", "admin"]:
                raise ForbiddenError("Permission denied")

        # Check if member already exists
        existing = await self.member_repo.get_by_page_and_user(page_id, member_data.user_id)
        if existing:
            raise ForbiddenError("User is already a member")

        member = await self.member_repo.create(
            page_id=page_id,
            user_id=member_data.user_id,
            role=member_data.role,
        )
        await self.db.commit()
        await self.db.refresh(member)

        return PageMemberResponse.model_validate(member)

    async def remove_member(self, page_id: UUID, user_id: UUID, current_user: User) -> None:
        """
        Remove member from page.

        Args:
            page_id: Page ID
            user_id: User ID to remove
            current_user: Current user

        Raises:
            NotFoundError: If page or member not found
            ForbiddenError: If user doesn't have permission
        """
        page = await self.page_repo.get_by_id(page_id)
        if not page or page.deleted_at:
            raise NotFoundError("Page not found")

        # Check permission (only owner or admin can remove members)
        if page.owner_id != current_user.id:
            member = await self.member_repo.get_by_page_and_user(page_id, current_user.id)
            if not member or member.role not in ["owner", "admin"]:
                raise ForbiddenError("Permission denied")

        member = await self.member_repo.get_by_page_and_user(page_id, user_id)
        if not member:
            raise NotFoundError("Member not found")

        # Can't remove owner
        if page.owner_id == user_id:
            raise ForbiddenError("Cannot remove page owner")

        await self.member_repo.delete(member.id)
        await self.db.commit()

    async def get_page_members(self, page_id: UUID, user: User) -> List[PageMemberResponse]:
        """
        Get all members of a page.

        Args:
            page_id: Page ID
            user: Current user

        Returns:
            List[PageMemberResponse]: List of page members

        Raises:
            NotFoundError: If page not found
            ForbiddenError: If user doesn't have access
        """
        page = await self.page_repo.get_by_id(page_id)
        if not page or page.deleted_at:
            raise NotFoundError("Page not found")

        # Check access (must be member or owner)
        if page.owner_id != user.id:
            member = await self.member_repo.get_by_page_and_user(page_id, user.id)
            if not member:
                # Check crew membership for collaborative pages
                if page.crew_id:
                    from src.repositories.crew import CrewMemberRepository

                    crew_member_repo = CrewMemberRepository(self.db)
                    crew_member = await crew_member_repo.get_by_crew_and_user(
                        page.crew_id, user.id
                    )
                    if not crew_member:
                        raise NotFoundError("Page not found")
                else:
                    raise NotFoundError("Page not found")

        members = await self.member_repo.get_page_members(page_id)
        return [PageMemberResponse.model_validate(m) for m in members]

    async def update_member_role(
        self, page_id: UUID, user_id: UUID, new_role: str, current_user: User
    ) -> PageMemberResponse:
        """
        Update member role in page.

        Args:
            page_id: Page ID
            user_id: User ID to update
            new_role: New role
            current_user: Current user

        Returns:
            PageMemberResponse: Updated member

        Raises:
            NotFoundError: If page or member not found
            ForbiddenError: If user doesn't have permission
        """
        page = await self.page_repo.get_by_id(page_id)
        if not page or page.deleted_at:
            raise NotFoundError("Page not found")

        # Check permission (only owner or admin can update roles)
        if page.owner_id != current_user.id:
            member = await self.member_repo.get_by_page_and_user(page_id, current_user.id)
            if not member or member.role not in ["owner", "admin"]:
                raise ForbiddenError("Permission denied")

        member = await self.member_repo.get_by_page_and_user(page_id, user_id)
        if not member:
            raise NotFoundError("Member not found")

        # Can't change owner role
        if page.owner_id == user_id:
            raise ForbiddenError("Cannot change page owner role")

        # Validate role
        if new_role not in ["admin", "member", "viewer"]:
            raise ForbiddenError("Invalid role")

        member.role = new_role
        await self.db.commit()
        await self.db.refresh(member)

        return PageMemberResponse.model_validate(member)

    async def get_user_page_or_404(self, page_id: UUID, user_id: UUID) -> Page:
        """
        Get page by ID and verify user access.
        Used for backend validation of tenant isolation.

        Args:
            page_id: Page ID
            user_id: User ID

        Returns:
            Page: Page model

        Raises:
            NotFoundError: If page not found
            ForbiddenError: If user doesn't have access
        """
        page = await self.page_repo.get_by_id(page_id)
        if not page or page.deleted_at:
            raise NotFoundError("Page not found")

        # Check if user is owner or member
        if page.owner_id != user_id:
            member = await self.member_repo.get_by_page_and_user(page_id, user_id)
            if not member:
                # We return 404 instead of 403 to prevent ID enumeration
                # but for internal service logic, ForbiddenError might be clearer.
                # However, the plan says 404 to avoid enumeration.
                raise NotFoundError("Page not found")

        return page
