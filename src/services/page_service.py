"""Page service."""

import json
from datetime import datetime, timezone
from typing import Any, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


def _deep_copy_json(value: Any) -> Any:
    """Deep-copy a JSON-serialisable value via round-trip.

    Used when cloning widget.data / widget.config so the new row doesn't
    share nested dict/list references with the source row.
    """
    if value is None:
        return None
    return json.loads(json.dumps(value))


from src.core.exceptions import ForbiddenError, NotFoundError
from src.models.page import Page
from src.models.user import User
from src.repositories.widget import WidgetRepository
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
        self.widget_repo = WidgetRepository(db)

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

        space_id = getattr(page_data, "space_id", None)

        page = await self.page_repo.create(
            name=page_data.name,
            description=page_data.description,
            type=page_data.type,
            color=page_data.color,
            icon=page_data.icon,
            owner_id=user.id,
            crew_id=crew_id,
            space_id=space_id,
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

        # Ingest the page into the RAG so chat/agents know about it.
        # Personal pages carry owner_user_id only so they stay isolated
        # per-user even if they later get moved under a space. Failures
        # are logged + swallowed — creation must never be blocked.
        try:
            import logging
            from src.ai.http_client import AIServiceHTTPClient
            _logger = logging.getLogger(__name__)
            ai_client = AIServiceHTTPClient()
            is_personal = page.type == "personal"
            await ai_client.ingest_knowledge_graph({
                "id": str(page.id),
                "entity_type": "page",
                "name": page.name,
                "description": page.description,
                "space_id": str(page.space_id) if page.space_id else None,
                "crew_id": str(page.crew_id) if page.crew_id else None,
                "owner_user_id": str(user.id) if is_personal else None,
                "entity_details": {
                    "type": page.type,
                    "color": page.color,
                    "icon": page.icon,
                    "owner_id": str(page.owner_id),
                },
            })
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(f"AI ingest failed for page {page.id}: {exc}")

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
                    crew_member = await crew_member_repo.get_by_crew_and_user(page.crew_id, user.id)
                    if not crew_member:
                        raise NotFoundError("Page not found")
                else:
                    raise NotFoundError("Page not found")

        return PageResponse.model_validate(page)

    async def get_user_pages(
        self,
        user: User,
        context: str = "all",
        space_id: Optional[UUID] = None,
        crew_id: Optional[UUID] = None,
    ) -> List[PageResponse]:
        """
        Get pages filtered by navigation context.

        Args:
            user: Current user
            context: "personal", "space", "crew", or "all"
            space_id: Required when context="space"
            crew_id: Required when context="crew"

        Returns:
            List[PageResponse]: Filtered pages
        """
        pages = await self.page_repo.get_user_pages(
            user.id, context=context, space_id=space_id, crew_id=crew_id
        )
        return [PageResponse.model_validate(w) for w in pages]

    async def update_page(self, page_id: UUID, user: User, page_data: PageUpdate) -> PageResponse:
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

    async def duplicate_page(self, page_id: UUID, user: User) -> PageResponse:
        """Duplicate a page with all its dashboards and widgets.

        Creates a fresh Page row (new UUID, name suffixed " (Copy)"), clones
        each Dashboard belonging to the source page (fresh UUIDs + canvas
        settings copy + `is_locked=False`) and for each dashboard re-creates
        every Widget with fresh UUIDs. `connection_id` / `query_id` are
        REFERENCED, not deep-copied, so the duplicated page points at the
        same data sources and saved queries as the original.

        Only copies what the current user can see; member roles and comments
        are not copied.

        Raises:
            NotFoundError: source page missing or soft-deleted.
            ForbiddenError: user is neither owner nor a member.
        """
        original = await self.page_repo.get_by_id(page_id)
        if not original or original.deleted_at:
            raise NotFoundError("Page not found")

        if original.owner_id != user.id:
            member = await self.member_repo.get_by_page_and_user(page_id, user.id)
            if not member:
                raise ForbiddenError("Permission denied")

        # 1. Create the new page — absorbs canvas_settings + template_id
        new_page = await self.page_repo.create(
            name=f"{original.name} (Copy)",
            description=original.description,
            type=original.type,
            color=original.color,
            icon=original.icon,
            owner_id=user.id,  # new owner = the duplicator
            crew_id=original.crew_id,
            space_id=original.space_id,
            is_active=False,
            canvas_settings=(
                original.canvas_settings.copy() if original.canvas_settings else None
            ),
            is_locked=False,  # copies always start unlocked
            template_id=original.template_id,
        )
        await self.db.flush()

        # Duplicator is the owner of the copy
        await self.member_repo.create(
            page_id=new_page.id,
            user_id=user.id,
            role="owner",
        )

        # 2. Clone widgets (infographics included — they are `type='infographic'`
        # rows in the same widgets table). Dashboard layer dropped 2026-05-20;
        # widgets attach directly to pages now.
        original_widgets = await self.widget_repo.get_by_page(page_id)
        for original_widget in original_widgets:
            # Deep copy via json round-trip so nested dicts/lists don't share
            # references with the original row.
            cloned_data = _deep_copy_json(original_widget.data)
            cloned_config = _deep_copy_json(original_widget.config)

            # Defensive: if the original widget was left in a transient
            # loading state (infographic AI save race, aborted generation,
            # etc.), strip `isLoading:true` on the clone.
            if isinstance(cloned_data, dict) and cloned_data.get("isLoading"):
                cloned_data["isLoading"] = False
            if isinstance(cloned_config, dict) and cloned_config.get("isLoading"):
                cloned_config["isLoading"] = False

            await self.widget_repo.create(
                page_id=new_page.id,
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
                data=cloned_data,
                config=cloned_config,
                connection_id=original_widget.connection_id,
                query_id=original_widget.query_id,
                z_index=getattr(original_widget, "z_index", 0) or 0,
                created_by=user.id,
            )

        await self.db.commit()
        await self.db.refresh(new_page)

        return PageResponse.model_validate(new_page)

    async def delete_page(self, page_id: UUID, user: User) -> None:
        """
        Delete page.

        Personal page: only the owner (``owner_id``) may delete.
        Space page: owner OR someone with pages.delete in the page's
        space (space owner / platform admin).

        Red-team HI-003 (2026-04-23): before this, Space-scoped pages
        could only be deleted by the creator, leaving admin cleanup
        impossible — product rule says "Space admin can delete
        anything in their Space".
        """
        page = await self.page_repo.get_by_id(page_id)
        if not page or page.deleted_at:
            raise NotFoundError("Page not found")

        # Personal: owner-only (map owner_id onto the guard's
        # owner_user_id shape).
        if getattr(page, "space_id", None) is None:
            if page.owner_id != user.id:
                raise ForbiddenError("Only page owner can delete")
        else:
            # Space page — creator bypass + RBAC pages.delete in the
            # page's space.
            if page.owner_id != user.id:
                from src.services.rbac_service import RBACService
                await RBACService(self.db).assert_permission(
                    user, "pages.delete", space_id=page.space_id
                )

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
                    crew_member = await crew_member_repo.get_by_crew_and_user(page.crew_id, user.id)
                    if not crew_member:
                        raise NotFoundError("Page not found")
                else:
                    raise NotFoundError("Page not found")

        # Deactivate all other pages for this user
        from sqlalchemy import update

        await self.db.execute(
            update(Page).where(Page.owner_id == user.id, Page.id != page_id).values(is_active=False)
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

        # Notify the new member they've been added to the page
        try:
            from src.schemas.notification import NotificationCreate
            from src.services.notification_service import NotificationService

            notif_svc = NotificationService(self.db)
            await notif_svc.create(
                NotificationCreate(
                    user_id=member_data.user_id,
                    type="page_member_added",
                    title=f"You were added to '{page.name}'",
                    description=f"{user.name or user.email} added you as {member_data.role}",
                    entity_type="page",
                    entity_id=str(page_id),
                    deep_link=f"/dashboard?page={page_id}",
                )
            )
        except Exception:
            pass  # Non-fatal — don't block the membership operation

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
                    crew_member = await crew_member_repo.get_by_crew_and_user(page.crew_id, user.id)
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

        # Check if user is owner or direct member
        if page.owner_id != user_id:
            member = await self.member_repo.get_by_page_and_user(page_id, user_id)
            if not member:
                # Check crew membership for collaborative pages
                if page.crew_id:
                    from src.repositories.crew import CrewMemberRepository

                    crew_member_repo = CrewMemberRepository(self.db)
                    crew_member = await crew_member_repo.get_by_crew_and_user(page.crew_id, user_id)
                    if not crew_member:
                        raise NotFoundError("Page not found")
                else:
                    raise NotFoundError("Page not found")

        return page
