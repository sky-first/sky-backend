"""Option B — page child-resource access gate (2026-06-16).

Comments, conversations, chat-sessions and export hang off a Page. They used
to check only the RBAC verb (`pages.view`), never whether the caller could
actually reach the page — so a NON-member could read/write the content of a
crew page they don't belong to. Each endpoint now calls
`PageService.get_page` (owner / page member / crew member / space member, with
the same crew fallback the page GET uses), which 404s a non-member.

These tests assert, per endpoint group: a crew member is allowed, an outsider
(authenticated, but not in the crew/space) is denied with 404.
"""

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token, get_password_hash
from src.models.crew import Crew, CrewMember
from src.models.page import Page
from src.models.space import Space, SpaceMember
from src.repositories.user import UserRepository


def _hdr(user) -> dict:
    token = create_access_token(
        {"sub": str(user.id), "email": user.email, "role": user.role}
    )
    return {"Authorization": f"Bearer {token}"}


async def _user(db: AsyncSession, email: str, role: str = "user"):
    user = await UserRepository(db).create(
        email=email,
        password_hash=get_password_hash("password123"),
        name=email.split("@")[0],
        role=role,
    )
    await db.commit()
    return user


async def _crew_page(db: AsyncSession):
    """Owner + member in a crew, plus an outsider, and the crew's shared page."""
    owner = await _user(db, "owner-child@example.com")
    member = await _user(db, "member-child@example.com")
    outsider = await _user(db, "outsider-child@example.com")

    space = Space(name="Space", created_by=owner.id)
    db.add(space)
    await db.commit()
    await db.refresh(space)
    db.add(SpaceMember(space_id=space.id, user_id=owner.id))

    crew = Crew(name="Crew", space_id=space.id, created_by=owner.id)
    db.add(crew)
    await db.commit()
    await db.refresh(crew)
    db.add(CrewMember(crew_id=crew.id, user_id=owner.id, role="owner"))
    db.add(CrewMember(crew_id=crew.id, user_id=member.id, role="viewer"))

    page = Page(
        name="Team Canvas",
        type="team",
        color="#3b82f6",
        owner_id=owner.id,
        crew_id=crew.id,
    )
    db.add(page)
    await db.commit()
    await db.refresh(page)
    return member, outsider, page


@pytest.mark.asyncio
async def test_conversations_list_gated_on_page_access(
    async_client: AsyncClient, db_session: AsyncSession
):
    member, outsider, page = await _crew_page(db_session)
    url = f"/api/v1/pages/{page.id}/conversations"
    assert (await async_client.get(url, headers=_hdr(member))).status_code == status.HTTP_200_OK
    assert (await async_client.get(url, headers=_hdr(outsider))).status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_conversation_create_gated_on_page_access(
    async_client: AsyncClient, db_session: AsyncSession
):
    member, outsider, page = await _crew_page(db_session)
    url = f"/api/v1/pages/{page.id}/conversations"
    assert (await async_client.post(url, json={}, headers=_hdr(member))).status_code == status.HTTP_201_CREATED
    assert (await async_client.post(url, json={}, headers=_hdr(outsider))).status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_chat_sessions_list_gated_on_page_access(
    async_client: AsyncClient, db_session: AsyncSession
):
    member, outsider, page = await _crew_page(db_session)
    url = f"/api/v1/pages/{page.id}/chat-sessions"
    assert (await async_client.get(url, headers=_hdr(member))).status_code == status.HTTP_200_OK
    assert (await async_client.get(url, headers=_hdr(outsider))).status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_chat_session_create_gated_on_page_access(
    async_client: AsyncClient, db_session: AsyncSession
):
    member, outsider, page = await _crew_page(db_session)
    url = f"/api/v1/pages/{page.id}/chat-sessions"
    assert (await async_client.post(url, json={}, headers=_hdr(member))).status_code == status.HTTP_201_CREATED
    assert (await async_client.post(url, json={}, headers=_hdr(outsider))).status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_comments_list_gated_on_page_access(
    async_client: AsyncClient, db_session: AsyncSession
):
    member, outsider, page = await _crew_page(db_session)
    url = f"/api/v1/comments?page_id={page.id}"
    assert (await async_client.get(url, headers=_hdr(member))).status_code == status.HTTP_200_OK
    assert (await async_client.get(url, headers=_hdr(outsider))).status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_export_gated_on_page_access(
    async_client: AsyncClient, db_session: AsyncSession
):
    member, outsider, page = await _crew_page(db_session)
    url = f"/api/v1/pages/{page.id}/export"
    assert (await async_client.post(url, headers=_hdr(member))).status_code == status.HTTP_200_OK
    assert (await async_client.post(url, headers=_hdr(outsider))).status_code == status.HTTP_404_NOT_FOUND
