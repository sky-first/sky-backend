"""Onboarding helpers to ensure default page for new users.

Default Space creation was removed in favour of Personal-first onboarding
— a fresh Owner no longer gets an auto-generated "Default space". They
start in Personal mode and create a Space on demand when they need
shared scope.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User
from src.repositories.page import PageMemberRepository, PageRepository


async def ensure_default_page_and_space(db: AsyncSession, user: User) -> None:
    """
    Ensure a user has at least one Personal page.

    Idempotent: if the user already owns a page, it does nothing.
    """
    page_repo = PageRepository(db)
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

    # Default space creation removed — Personal-first onboarding. The
    # page above is enough to start. Connections / agents / rules
    # created in Personal can be promoted to a Space later.

    await db.commit()
    await db.refresh(page)
