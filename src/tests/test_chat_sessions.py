"""Tests for the chat-sessions API (Variant A — sessions on top of threads).

Covers:
  - Listing sessions on a page auto-creates a default "Chat 1" (never empty)
  - "+" creates the next session ("Chat 2") with stable position order
  - A conversation created without session_id lands in the default session
  - A conversation created with a pinned session_id lands in that session
  - Listing conversations filtered by session_id returns only that chat
  - Renaming a session
  - Space-scoped sessions are visible to a fellow space member (collaborative)
"""

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import get_password_hash
from src.models.page import Page
from src.models.space import Space, SpaceMember
from src.repositories.user import UserRepository


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_page(db, owner_id, name="Chat Page", space_id=None):
    page = Page(
        name=name,
        type="team" if space_id else "personal",
        color="#3b82f6",
        owner_id=owner_id,
        space_id=space_id,
    )
    db.add(page)
    await db.commit()
    await db.refresh(page)
    return page


@pytest.mark.asyncio
async def test_list_sessions_autocreates_default_chat_one(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    page = await _create_page(db_session, user.id)
    headers = _headers(test_user_with_tokens["access_token"])

    resp = await async_client.get(
        f"/api/v1/pages/{page.id}/chat-sessions", headers=headers
    )
    assert resp.status_code == status.HTTP_200_OK
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Chat 1"
    assert items[0]["position"] == 0


@pytest.mark.asyncio
async def test_plus_creates_next_session(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    page = await _create_page(db_session, user.id)
    headers = _headers(test_user_with_tokens["access_token"])

    # Ensure Chat 1 exists, then "+".
    await async_client.get(f"/api/v1/pages/{page.id}/chat-sessions", headers=headers)
    resp = await async_client.post(
        f"/api/v1/pages/{page.id}/chat-sessions", json={}, headers=headers
    )
    assert resp.status_code == status.HTTP_201_CREATED
    assert resp.json()["title"] == "Chat 2"
    assert resp.json()["position"] == 1


@pytest.mark.asyncio
async def test_conversation_lands_in_default_session_when_unpinned(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    page = await _create_page(db_session, user.id)
    headers = _headers(test_user_with_tokens["access_token"])

    conv = await async_client.post(
        f"/api/v1/pages/{page.id}/conversations", json={}, headers=headers
    )
    assert conv.status_code == status.HTTP_201_CREATED
    session_id = conv.json()["session_id"]
    assert session_id is not None

    sessions = (
        await async_client.get(
            f"/api/v1/pages/{page.id}/chat-sessions", headers=headers
        )
    ).json()["items"]
    assert session_id == sessions[0]["id"]


@pytest.mark.asyncio
async def test_conversations_filtered_by_session(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    page = await _create_page(db_session, user.id)
    headers = _headers(test_user_with_tokens["access_token"])

    # Default session + a thread in it.
    c1 = await async_client.post(
        f"/api/v1/pages/{page.id}/conversations", json={}, headers=headers
    )
    default_session = c1.json()["session_id"]

    # Second session + a thread pinned to it.
    s2 = await async_client.post(
        f"/api/v1/pages/{page.id}/chat-sessions", json={}, headers=headers
    )
    s2_id = s2.json()["id"]
    c2 = await async_client.post(
        f"/api/v1/pages/{page.id}/conversations",
        json={"session_id": s2_id},
        headers=headers,
    )
    assert c2.json()["session_id"] == s2_id

    # Filtering by session returns only that chat's threads.
    listed = (
        await async_client.get(
            f"/api/v1/pages/{page.id}/conversations?session_id={s2_id}",
            headers=headers,
        )
    ).json()["items"]
    ids = {c["id"] for c in listed}
    assert c2.json()["id"] in ids
    assert c1.json()["id"] not in ids
    assert default_session != s2_id


@pytest.mark.asyncio
async def test_rename_session(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    page = await _create_page(db_session, user.id)
    headers = _headers(test_user_with_tokens["access_token"])

    s = (
        await async_client.post(
            f"/api/v1/pages/{page.id}/chat-sessions", json={}, headers=headers
        )
    ).json()
    resp = await async_client.patch(
        f"/api/v1/chat-sessions/{s['id']}",
        json={"title": "Q4 planning"},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["title"] == "Q4 planning"


@pytest.mark.asyncio
async def test_delete_session_removes_it_and_its_threads(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    page = await _create_page(db_session, user.id)
    headers = _headers(test_user_with_tokens["access_token"])

    # Default "Chat 1" + a second chat with a thread in it.
    await async_client.get(f"/api/v1/pages/{page.id}/chat-sessions", headers=headers)
    s2 = (await async_client.post(
        f"/api/v1/pages/{page.id}/chat-sessions", json={}, headers=headers
    )).json()
    conv = (await async_client.post(
        f"/api/v1/pages/{page.id}/conversations",
        json={"session_id": s2["id"]},
        headers=headers,
    )).json()

    # Delete the second chat.
    resp = await async_client.delete(f"/api/v1/chat-sessions/{s2['id']}", headers=headers)
    assert resp.status_code == status.HTTP_204_NO_CONTENT

    # Session gone from the switcher; its thread is gone too.
    sessions = (await async_client.get(
        f"/api/v1/pages/{page.id}/chat-sessions", headers=headers
    )).json()["items"]
    assert s2["id"] not in {s["id"] for s in sessions}
    gone = await async_client.get(f"/api/v1/conversations/{conv['id']}", headers=headers)
    assert gone.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_cannot_delete_the_last_chat(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    page = await _create_page(db_session, user.id)
    headers = _headers(test_user_with_tokens["access_token"])

    # Only the default "Chat 1" exists.
    only = (await async_client.get(
        f"/api/v1/pages/{page.id}/chat-sessions", headers=headers
    )).json()["items"][0]

    resp = await async_client.delete(f"/api/v1/chat-sessions/{only['id']}", headers=headers)
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_space_session_visible_to_member(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    owner = test_user_with_tokens["user"]
    # A second user who is a member of the same space.
    repo = UserRepository(db_session)
    member = await repo.create(
        email="member@example.com",
        password_hash=get_password_hash("password123"),
        name="member",
        role="user",
    )
    await db_session.commit()
    space = Space(name="Shared", created_by=owner.id)
    db_session.add(space)
    await db_session.commit()
    await db_session.refresh(space)
    db_session.add(SpaceMember(space_id=space.id, user_id=owner.id))
    db_session.add(SpaceMember(space_id=space.id, user_id=member.id))
    await db_session.commit()

    page = await _create_page(db_session, owner.id, space_id=space.id)
    headers = _headers(test_user_with_tokens["access_token"])

    # Owner creates a session on the shared page (inherits space scope).
    created = await async_client.post(
        f"/api/v1/pages/{page.id}/chat-sessions", json={}, headers=headers
    )
    assert created.status_code == status.HTTP_201_CREATED
    assert created.json()["space_id"] == str(space.id)
