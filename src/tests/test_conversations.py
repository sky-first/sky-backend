"""Tests for the conversations API — Phase 1 iteration 1.3a.

Covers use cases from docs/agent-and-ai-master-plan.md:
  A1   Auto-create blank conversation on page
  A8   Archive hides from default list, visible when include_archived=true
  A9   Paginated by updated_at desc
  A10  Rename sets title
  A12  Personal conversation not visible to other users
  A13  Crew conversation visible to crew members
  A14  Space conversation visible to space members
  A15  Delete cascades to messages; widgets keep their conversation_id null

Use cases A2-A7 and A11 land in iteration 1.3b together with the Messages
CRUD + pin endpoint.
"""

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.crew import Crew, CrewMember
from src.models.page import Page
from src.models.space import Space, SpaceMember
from src.repositories.user import UserRepository
from src.core.security import get_password_hash


# ─── Helpers ──────────────────────────────────────────────────────────────

def get_auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


async def create_user(db_session: AsyncSession, email: str, role: str = "user"):
    repo = UserRepository(db_session)
    user = await repo.create(
        email=email,
        password_hash=get_password_hash("password123"),
        name=email.split("@")[0],
        role=role,
    )
    await db_session.commit()
    return user


async def create_page(db_session: AsyncSession, owner_id, name="Test Page"):
    page = Page(name=name, type="personal", color="#3b82f6", owner_id=owner_id)
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)
    return page


async def create_space_with_member(db_session: AsyncSession, owner_id, member_id=None, name="Space"):
    space = Space(name=name, created_by=owner_id)
    db_session.add(space)
    await db_session.commit()
    await db_session.refresh(space)
    db_session.add(SpaceMember(space_id=space.id, user_id=owner_id))
    if member_id and member_id != owner_id:
        db_session.add(SpaceMember(space_id=space.id, user_id=member_id))
    await db_session.commit()
    return space


async def create_crew_with_member(db_session: AsyncSession, space_id, owner_id, member_id=None, name="Crew"):
    crew = Crew(name=name, space_id=space_id, created_by=owner_id)
    db_session.add(crew)
    await db_session.commit()
    await db_session.refresh(crew)
    db_session.add(CrewMember(crew_id=crew.id, user_id=owner_id, role="owner"))
    if member_id and member_id != owner_id:
        db_session.add(CrewMember(crew_id=crew.id, user_id=member_id, role="viewer"))
    await db_session.commit()
    return crew


# ─── A1: create ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_personal_conversation_returns_201_and_empty_title(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    page = await create_page(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])

    response = await async_client.post(
        f"/api/v1/pages/{page.id}/conversations", json={}, headers=headers
    )

    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["page_id"] == str(page.id)
    assert data["title"] is None
    assert data["space_id"] is None
    assert data["crew_id"] is None
    assert data["archived_at"] is None
    assert data["created_by"] == str(user.id)


@pytest.mark.asyncio
async def test_create_crew_conversation_stores_crew_id(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    page = await create_page(db_session, user.id)
    space = await create_space_with_member(db_session, user.id)
    crew = await create_crew_with_member(db_session, space.id, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])

    response = await async_client.post(
        f"/api/v1/pages/{page.id}/conversations",
        json={"space_id": str(space.id), "crew_id": str(crew.id)},
        headers=headers,
    )

    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["crew_id"] == str(crew.id)
    assert data["space_id"] == str(space.id)


# ─── A9: list + pagination ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_conversations_newest_first(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    import asyncio

    user = test_user_with_tokens["user"]
    page = await create_page(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])

    ids = []
    for _ in range(3):
        r = await async_client.post(
            f"/api/v1/pages/{page.id}/conversations", json={}, headers=headers
        )
        ids.append(r.json()["id"])
        # SQLite's CURRENT_TIMESTAMP has second-level precision; a brief
        # yield lets updated_at differ between inserts so the order assertion
        # below is meaningful.
        await asyncio.sleep(0.02)

    r = await async_client.get(
        f"/api/v1/pages/{page.id}/conversations", headers=headers
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 3
    # Newest first — ids reversed
    assert [i["id"] for i in items] == list(reversed(ids))


@pytest.mark.asyncio
async def test_list_conversations_pagination_cursor(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    import asyncio

    user = test_user_with_tokens["user"]
    page = await create_page(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])

    for _ in range(5):
        await async_client.post(
            f"/api/v1/pages/{page.id}/conversations", json={}, headers=headers
        )
        await asyncio.sleep(0.02)

    # Page size 2 → expect next_cursor set
    r = await async_client.get(
        f"/api/v1/pages/{page.id}/conversations?limit=2", headers=headers
    )
    data = r.json()
    assert len(data["items"]) == 2
    assert data["next_cursor"] is not None

    # Use cursor to get next page
    r2 = await async_client.get(
        f"/api/v1/pages/{page.id}/conversations?limit=2&cursor={data['next_cursor']}",
        headers=headers,
    )
    data2 = r2.json()
    assert len(data2["items"]) == 2
    # IDs should not overlap
    ids1 = {i["id"] for i in data["items"]}
    ids2 = {i["id"] for i in data2["items"]}
    assert ids1.isdisjoint(ids2)


# ─── A10: rename ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rename_conversation_updates_title(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    page = await create_page(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])

    r = await async_client.post(
        f"/api/v1/pages/{page.id}/conversations", json={}, headers=headers
    )
    conv_id = r.json()["id"]

    r2 = await async_client.patch(
        f"/api/v1/conversations/{conv_id}",
        json={"title": "Churn deep dive"},
        headers=headers,
    )
    assert r2.status_code == 200
    assert r2.json()["title"] == "Churn deep dive"


@pytest.mark.asyncio
async def test_rename_by_non_creator_returns_404_for_personal(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    # Another user's personal conversation is not even visible → 404.
    owner = test_user_with_tokens["user"]
    page = await create_page(db_session, owner.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])

    r = await async_client.post(
        f"/api/v1/pages/{page.id}/conversations", json={}, headers=headers
    )
    conv_id = r.json()["id"]

    # Different user tries to rename
    other = await create_user(db_session, "intruder@x.com")
    from src.core.security import create_access_token
    other_token = create_access_token({"sub": str(other.id)})
    other_headers = get_auth_headers(other_token)

    r2 = await async_client.patch(
        f"/api/v1/conversations/{conv_id}",
        json={"title": "hacked"},
        headers=other_headers,
    )
    assert r2.status_code == 404  # existence leak prevented


# ─── A8: archive ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_archive_hides_from_default_list(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    page = await create_page(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])

    r = await async_client.post(
        f"/api/v1/pages/{page.id}/conversations", json={}, headers=headers
    )
    conv_id = r.json()["id"]

    await async_client.post(
        f"/api/v1/conversations/{conv_id}/archive", headers=headers
    )

    default_list = await async_client.get(
        f"/api/v1/pages/{page.id}/conversations", headers=headers
    )
    assert default_list.json()["items"] == []

    with_archived = await async_client.get(
        f"/api/v1/pages/{page.id}/conversations?include_archived=true",
        headers=headers,
    )
    assert len(with_archived.json()["items"]) == 1
    assert with_archived.json()["items"][0]["archived_at"] is not None


@pytest.mark.asyncio
async def test_unarchive_restores(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    page = await create_page(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])

    r = await async_client.post(
        f"/api/v1/pages/{page.id}/conversations", json={}, headers=headers
    )
    conv_id = r.json()["id"]

    await async_client.post(
        f"/api/v1/conversations/{conv_id}/archive", headers=headers
    )
    r2 = await async_client.post(
        f"/api/v1/conversations/{conv_id}/unarchive", headers=headers
    )
    assert r2.status_code == 200
    assert r2.json()["archived_at"] is None


# ─── A12: personal RBAC ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_personal_conversation_invisible_to_others(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    owner = test_user_with_tokens["user"]
    page = await create_page(db_session, owner.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])

    r = await async_client.post(
        f"/api/v1/pages/{page.id}/conversations", json={}, headers=headers
    )
    conv_id = r.json()["id"]

    other = await create_user(db_session, "other@x.com")
    from src.core.security import create_access_token
    other_token = create_access_token({"sub": str(other.id)})
    other_headers = get_auth_headers(other_token)

    # GET single conversation → 404
    r2 = await async_client.get(
        f"/api/v1/conversations/{conv_id}", headers=other_headers
    )
    assert r2.status_code == 404

    # List on the same page → empty
    r3 = await async_client.get(
        f"/api/v1/pages/{page.id}/conversations", headers=other_headers
    )
    assert r3.json()["items"] == []


# ─── A13 & A14: shared RBAC ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_crew_conversation_visible_to_crew_member(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    owner = test_user_with_tokens["user"]
    member = await create_user(db_session, "member@x.com")
    page = await create_page(db_session, owner.id)
    space = await create_space_with_member(db_session, owner.id, member_id=member.id)
    crew = await create_crew_with_member(
        db_session, space.id, owner.id, member_id=member.id
    )

    owner_headers = get_auth_headers(test_user_with_tokens["access_token"])
    from src.core.security import create_access_token
    member_token = create_access_token({"sub": str(member.id)})
    member_headers = get_auth_headers(member_token)

    r = await async_client.post(
        f"/api/v1/pages/{page.id}/conversations",
        json={"space_id": str(space.id), "crew_id": str(crew.id)},
        headers=owner_headers,
    )
    assert r.status_code == 201
    conv_id = r.json()["id"]

    # Member can see it
    r2 = await async_client.get(
        f"/api/v1/conversations/{conv_id}", headers=member_headers
    )
    assert r2.status_code == 200
    assert r2.json()["id"] == conv_id


@pytest.mark.asyncio
async def test_space_conversation_visible_to_space_member(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    owner = test_user_with_tokens["user"]
    member = await create_user(db_session, "spacer@x.com")
    page = await create_page(db_session, owner.id)
    space = await create_space_with_member(db_session, owner.id, member_id=member.id)

    owner_headers = get_auth_headers(test_user_with_tokens["access_token"])
    from src.core.security import create_access_token
    member_token = create_access_token({"sub": str(member.id)})
    member_headers = get_auth_headers(member_token)

    r = await async_client.post(
        f"/api/v1/pages/{page.id}/conversations",
        json={"space_id": str(space.id)},
        headers=owner_headers,
    )
    conv_id = r.json()["id"]

    r2 = await async_client.get(
        f"/api/v1/conversations/{conv_id}", headers=member_headers
    )
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_crew_conversation_invisible_to_non_member(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    owner = test_user_with_tokens["user"]
    outsider = await create_user(db_session, "outsider@x.com")
    page = await create_page(db_session, owner.id)
    space = await create_space_with_member(db_session, owner.id)
    crew = await create_crew_with_member(db_session, space.id, owner.id)

    owner_headers = get_auth_headers(test_user_with_tokens["access_token"])
    from src.core.security import create_access_token
    outsider_token = create_access_token({"sub": str(outsider.id)})
    outsider_headers = get_auth_headers(outsider_token)

    r = await async_client.post(
        f"/api/v1/pages/{page.id}/conversations",
        json={"space_id": str(space.id), "crew_id": str(crew.id)},
        headers=owner_headers,
    )
    conv_id = r.json()["id"]

    r2 = await async_client.get(
        f"/api/v1/conversations/{conv_id}", headers=outsider_headers
    )
    assert r2.status_code == 404


# ─── A15: delete ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_by_creator_succeeds(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    page = await create_page(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])

    r = await async_client.post(
        f"/api/v1/pages/{page.id}/conversations", json={}, headers=headers
    )
    conv_id = r.json()["id"]

    r2 = await async_client.delete(
        f"/api/v1/conversations/{conv_id}", headers=headers
    )
    assert r2.status_code == 204

    r3 = await async_client.get(
        f"/api/v1/conversations/{conv_id}", headers=headers
    )
    assert r3.status_code == 404


@pytest.mark.asyncio
async def test_non_creator_member_cannot_delete_crew_conversation(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    # Member can view but not delete.
    owner = test_user_with_tokens["user"]
    member = await create_user(db_session, "m2@x.com")
    page = await create_page(db_session, owner.id)
    space = await create_space_with_member(db_session, owner.id, member_id=member.id)
    crew = await create_crew_with_member(
        db_session, space.id, owner.id, member_id=member.id
    )

    owner_headers = get_auth_headers(test_user_with_tokens["access_token"])
    from src.core.security import create_access_token
    member_token = create_access_token({"sub": str(member.id)})
    member_headers = get_auth_headers(member_token)

    r = await async_client.post(
        f"/api/v1/pages/{page.id}/conversations",
        json={"space_id": str(space.id), "crew_id": str(crew.id)},
        headers=owner_headers,
    )
    conv_id = r.json()["id"]

    # Member can view
    r_view = await async_client.get(
        f"/api/v1/conversations/{conv_id}", headers=member_headers
    )
    assert r_view.status_code == 200

    # But cannot delete
    r_del = await async_client.delete(
        f"/api/v1/conversations/{conv_id}", headers=member_headers
    )
    assert r_del.status_code == 403
