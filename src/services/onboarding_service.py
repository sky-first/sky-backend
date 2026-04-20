"""Onboarding helpers to ensure default page/space for new users."""

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.space import SpaceMember
from src.models.user import User
from src.repositories.page import PageMemberRepository, PageRepository
from src.repositories.space import SpaceRepository


async def ensure_default_page_and_space(db: AsyncSession, user: User) -> None:
    """
    Ensure a user has at least one page and a default space.

    Idempotent: if the user already owns a page, it does nothing.
    """
    page_repo = PageRepository(db)
    space_repo = SpaceRepository(db)
    page_member_repo = PageMemberRepository(db)

    # Already has page? Do nothing.
    existing_pages = await page_repo.get_by_owner(user.id, limit=1)
    if existing_pages:
        return

    # Create a default page
    page_name = f"{user.name.split(' ')[0]}'s page" if user.name else "My first page"
    page = await page_repo.create(
        name=page_name,
        description="Your first page",
        type="personal",
        color="#3B82F6",  # default blue
        icon=None,
        owner_id=user.id,
        is_active=True,
    )

    # Add the user as owner/member
    await page_member_repo.create(
        page_id=page.id,
        user_id=user.id,
        role="owner",
    )

    # Create a default space AND add the user as a member. Previously we
    # created the Space with `created_by=user.id` but never inserted a
    # SpaceMember row — the Space showed in the sidebar but the user
    # wasn't "inside" it, so member counts were 0 and the settings panel
    # rendered a blank Members tab. The creator is always a member of
    # their own default space.
    space = await space_repo.create(
        name="Default space",
        description="Your first space",
        color="#3B82F6",
        icon=None,
        created_by=user.id,
    )
    db.add(SpaceMember(space_id=space.id, user_id=user.id))

    await db.commit()
    await db.refresh(page)
