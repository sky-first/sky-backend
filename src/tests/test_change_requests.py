"""Tests for change-requests (chat-threads-master-plan PR3).

Lifecycle covered:
  - open a change request from a non-owner comment
  - widget-owner accepts → status='accepted'
  - widget-owner dismisses → status='dismissed'
  - non-owner cannot accept/dismiss → 403
  - cross-thread message rejected
  - re-resolving a non-pending CR returns 400
  - list per widget filters by status and reports pending_count
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token, get_password_hash
from src.models.page import Page
from src.models.space import Space, SpaceMember
from src.models.widget import Widget
from src.repositories.user import UserRepository


def get_auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def create_user(db_session: AsyncSession, email: str):
    repo = UserRepository(db_session)
    user = await repo.create(
        email=email,
        password_hash=get_password_hash("password123"),
        name=email.split("@")[0],
        role="user",
    )
    await db_session.commit()
    return user


async def seed_widget(db_session: AsyncSession, *, page_id, owner_id):
    w = Widget(
        page_id=page_id,
        type="chart",
        title="Sales by month",
        position={"x": 0, "y": 0},
        size={"width": 400, "height": 300},
        data={},
        created_by=owner_id,
    )
    db_session.add(w)
    await db_session.commit()
    await db_session.refresh(w)
    return w


async def seed_space_with_two_members(db_session: AsyncSession, owner):
    space = Space(name="S", created_by=owner.id)
    db_session.add(space)
    await db_session.commit()
    await db_session.refresh(space)
    db_session.add(SpaceMember(space_id=space.id, user_id=owner.id, role="owner"))
    other = await create_user(db_session, "other@example.com")
    db_session.add(SpaceMember(space_id=space.id, user_id=other.id, role="editor"))
    await db_session.commit()
    return space, other


async def make_conv(client, page_id, headers, body=None):
    r = await client.post(
        f"/api/v1/pages/{page_id}/conversations", json=body or {}, headers=headers
    )
    assert r.status_code == 201
    return r.json()


async def post_comment(client, conv_id, headers, content):
    r = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"role": "user", "kind": "comment", "content": content},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_open_change_request_from_non_owner_comment(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    owner = test_user_with_tokens["user"]
    owner_headers = get_auth_headers(test_user_with_tokens["access_token"])
    page = Page(name="P", type="personal", color="#3b82f6", owner_id=owner.id)
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)
    widget = await seed_widget(db_session, page_id=page.id, owner_id=owner.id)

    space, other = await seed_space_with_two_members(db_session, owner)
    other_token = create_access_token({"sub": str(other.id)})
    other_headers = get_auth_headers(other_token)

    conv = await make_conv(
        async_client, page.id, owner_headers, body={"space_id": str(space.id)}
    )
    comment = await post_comment(
        async_client, conv["id"], other_headers, "the y-axis label looks wrong on #1"
    )

    r = await async_client.post(
        "/api/v1/change-requests",
        json={
            "widget_id": str(widget.id),
            "conversation_id": conv["id"],
            "message_id": comment["id"],
            "content": "y-axis label looks wrong",
        },
        headers=other_headers,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["status"] == "pending"
    assert data["widget_id"] == str(widget.id)
    assert data["requester_id"] == str(other.id)


@pytest.mark.asyncio
async def test_widget_owner_accepts_change_request(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    owner = test_user_with_tokens["user"]
    owner_headers = get_auth_headers(test_user_with_tokens["access_token"])
    page = Page(name="P", type="personal", color="#3b82f6", owner_id=owner.id)
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)
    widget = await seed_widget(db_session, page_id=page.id, owner_id=owner.id)

    space, other = await seed_space_with_two_members(db_session, owner)
    other_token = create_access_token({"sub": str(other.id)})
    other_headers = get_auth_headers(other_token)

    conv = await make_conv(
        async_client, page.id, owner_headers, body={"space_id": str(space.id)}
    )
    comment = await post_comment(async_client, conv["id"], other_headers, "tip")

    r_create = await async_client.post(
        "/api/v1/change-requests",
        json={
            "widget_id": str(widget.id),
            "conversation_id": conv["id"],
            "message_id": comment["id"],
            "content": "tip",
        },
        headers=other_headers,
    )
    cr_id = r_create.json()["id"]

    r_accept = await async_client.post(
        f"/api/v1/change-requests/{cr_id}/accept", headers=owner_headers
    )
    assert r_accept.status_code == 200, r_accept.text
    assert r_accept.json()["status"] == "accepted"
    assert r_accept.json()["resolved_by"] == str(owner.id)


@pytest.mark.asyncio
async def test_widget_owner_dismisses_change_request(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    owner = test_user_with_tokens["user"]
    owner_headers = get_auth_headers(test_user_with_tokens["access_token"])
    page = Page(name="P", type="personal", color="#3b82f6", owner_id=owner.id)
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)
    widget = await seed_widget(db_session, page_id=page.id, owner_id=owner.id)

    space, other = await seed_space_with_two_members(db_session, owner)
    other_token = create_access_token({"sub": str(other.id)})
    other_headers = get_auth_headers(other_token)

    conv = await make_conv(
        async_client, page.id, owner_headers, body={"space_id": str(space.id)}
    )
    comment = await post_comment(async_client, conv["id"], other_headers, "tip")

    r_create = await async_client.post(
        "/api/v1/change-requests",
        json={
            "widget_id": str(widget.id),
            "conversation_id": conv["id"],
            "message_id": comment["id"],
            "content": "tip",
        },
        headers=other_headers,
    )
    cr_id = r_create.json()["id"]

    r_dismiss = await async_client.post(
        f"/api/v1/change-requests/{cr_id}/dismiss", headers=owner_headers
    )
    assert r_dismiss.status_code == 200, r_dismiss.text
    assert r_dismiss.json()["status"] == "dismissed"


@pytest.mark.asyncio
async def test_non_owner_cannot_accept(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    owner = test_user_with_tokens["user"]
    owner_headers = get_auth_headers(test_user_with_tokens["access_token"])
    page = Page(name="P", type="personal", color="#3b82f6", owner_id=owner.id)
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)
    widget = await seed_widget(db_session, page_id=page.id, owner_id=owner.id)

    space, other = await seed_space_with_two_members(db_session, owner)
    other_token = create_access_token({"sub": str(other.id)})
    other_headers = get_auth_headers(other_token)

    conv = await make_conv(
        async_client, page.id, owner_headers, body={"space_id": str(space.id)}
    )
    comment = await post_comment(async_client, conv["id"], other_headers, "tip")

    r_create = await async_client.post(
        "/api/v1/change-requests",
        json={
            "widget_id": str(widget.id),
            "conversation_id": conv["id"],
            "message_id": comment["id"],
            "content": "tip",
        },
        headers=other_headers,
    )
    cr_id = r_create.json()["id"]

    r_accept = await async_client.post(
        f"/api/v1/change-requests/{cr_id}/accept", headers=other_headers
    )
    assert r_accept.status_code == 403


@pytest.mark.asyncio
async def test_double_resolve_returns_400(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    owner = test_user_with_tokens["user"]
    owner_headers = get_auth_headers(test_user_with_tokens["access_token"])
    page = Page(name="P", type="personal", color="#3b82f6", owner_id=owner.id)
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)
    widget = await seed_widget(db_session, page_id=page.id, owner_id=owner.id)

    space, other = await seed_space_with_two_members(db_session, owner)
    other_token = create_access_token({"sub": str(other.id)})
    other_headers = get_auth_headers(other_token)

    conv = await make_conv(
        async_client, page.id, owner_headers, body={"space_id": str(space.id)}
    )
    comment = await post_comment(async_client, conv["id"], other_headers, "tip")

    r_create = await async_client.post(
        "/api/v1/change-requests",
        json={
            "widget_id": str(widget.id),
            "conversation_id": conv["id"],
            "message_id": comment["id"],
            "content": "tip",
        },
        headers=other_headers,
    )
    cr_id = r_create.json()["id"]

    await async_client.post(
        f"/api/v1/change-requests/{cr_id}/accept", headers=owner_headers
    )
    # Second attempt — already-accepted should reject.
    r2 = await async_client.post(
        f"/api/v1/change-requests/{cr_id}/dismiss", headers=owner_headers
    )
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_list_change_requests_for_widget_with_pending_count(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    owner = test_user_with_tokens["user"]
    owner_headers = get_auth_headers(test_user_with_tokens["access_token"])
    page = Page(name="P", type="personal", color="#3b82f6", owner_id=owner.id)
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)
    widget = await seed_widget(db_session, page_id=page.id, owner_id=owner.id)

    space, other = await seed_space_with_two_members(db_session, owner)
    other_token = create_access_token({"sub": str(other.id)})
    other_headers = get_auth_headers(other_token)

    conv = await make_conv(
        async_client, page.id, owner_headers, body={"space_id": str(space.id)}
    )

    # Open three change requests then dismiss the first.
    cr_ids = []
    for i in range(3):
        comment = await post_comment(
            async_client, conv["id"], other_headers, f"comment {i}"
        )
        r = await async_client.post(
            "/api/v1/change-requests",
            json={
                "widget_id": str(widget.id),
                "conversation_id": conv["id"],
                "message_id": comment["id"],
                "content": f"comment {i}",
            },
            headers=other_headers,
        )
        cr_ids.append(r.json()["id"])

    await async_client.post(
        f"/api/v1/change-requests/{cr_ids[0]}/dismiss", headers=owner_headers
    )

    r_list = await async_client.get(
        f"/api/v1/widgets/{widget.id}/change-requests", headers=owner_headers
    )
    assert r_list.status_code == 200
    body = r_list.json()
    assert len(body["items"]) == 3
    assert body["pending_count"] == 2


@pytest.mark.asyncio
async def test_cross_thread_message_rejected(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    owner = test_user_with_tokens["user"]
    owner_headers = get_auth_headers(test_user_with_tokens["access_token"])
    page = Page(name="P", type="personal", color="#3b82f6", owner_id=owner.id)
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)
    widget = await seed_widget(db_session, page_id=page.id, owner_id=owner.id)

    space, other = await seed_space_with_two_members(db_session, owner)
    other_token = create_access_token({"sub": str(other.id)})
    other_headers = get_auth_headers(other_token)

    conv_a = await make_conv(
        async_client, page.id, owner_headers, body={"space_id": str(space.id)}
    )
    conv_b = await make_conv(
        async_client, page.id, owner_headers, body={"space_id": str(space.id)}
    )
    comment_in_b = await post_comment(
        async_client, conv_b["id"], other_headers, "from B"
    )

    r = await async_client.post(
        "/api/v1/change-requests",
        json={
            "widget_id": str(widget.id),
            "conversation_id": conv_a["id"],
            "message_id": comment_in_b["id"],
            "content": "spoof",
        },
        headers=other_headers,
    )
    assert r.status_code == 404
