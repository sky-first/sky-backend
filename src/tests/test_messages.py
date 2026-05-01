"""Tests for messages + pin + fork — Phase 1 iteration 1.3b.

Use cases covered from docs/agent-and-ai-master-plan.md:
  A2   User message stored
  A3   Pin assistant message materialises a widget
  A6   Fork creates a new personal conversation from a branch point
  A7   Multiple pins in the same thread produce multiple widgets
  A11  Concurrent pin of the same message resolves to a single widget

Negative paths:
  - Pinning a user message is rejected
  - Creating a non-user message via HTTP is rejected (role enforcement)
  - Fork with unrelated message_id returns 400
  - Non-member cannot list messages in a crew conversation
"""

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token, get_password_hash
from src.models.conversation import Message
from src.models.dashboard import Dashboard, Widget
from src.models.page import Page
from src.models.space import Space, SpaceMember
from src.models.crew import Crew, CrewMember
from src.repositories.user import UserRepository


def get_auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


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


async def create_page_with_dashboard(db_session: AsyncSession, owner_id):
    page = Page(name="P", type="personal", color="#3b82f6", owner_id=owner_id)
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)
    dash = Dashboard(name="D", page_id=page.id, created_by=owner_id)
    db_session.add(dash)
    await db_session.commit()
    await db_session.refresh(dash)
    return page, dash


async def make_conversation(client: AsyncClient, page_id, headers, body=None):
    r = await client.post(
        f"/api/v1/pages/{page_id}/conversations",
        json=body or {},
        headers=headers,
    )
    assert r.status_code == status.HTTP_201_CREATED
    return r.json()


async def make_assistant_message(db_session: AsyncSession, conversation_id, content="answer"):
    """Insert an assistant message directly — the HTTP API rejects role=assistant."""
    from datetime import datetime as _dt
    from uuid import UUID as _UUID
    # API responses deliver UUIDs as strings; our model column is UUID.
    if isinstance(conversation_id, str):
        conversation_id = _UUID(conversation_id)
    msg = Message(
        conversation_id=conversation_id,
        role="assistant",
        content=content,
        created_at=_dt.utcnow(),
    )
    db_session.add(msg)
    await db_session.commit()
    await db_session.refresh(msg)
    return msg


# ─── A2: create user message ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_user_message_returns_201(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    page, _ = await create_page_with_dashboard(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])
    conv = await make_conversation(async_client, page["id"] if False else page.id, headers)

    r = await async_client.post(
        f"/api/v1/conversations/{conv['id']}/messages",
        json={"role": "user", "content": "What is our churn rate?"},
        headers=headers,
    )
    assert r.status_code == 201
    data = r.json()
    assert data["role"] == "user"
    assert data["content"] == "What is our churn rate?"
    assert data["conversation_id"] == conv["id"]
    assert data["pinned_widget_id"] is None


@pytest.mark.asyncio
async def test_create_assistant_message_via_http_rejected(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    page, _ = await create_page_with_dashboard(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])
    conv = await make_conversation(async_client, page.id, headers)

    r = await async_client.post(
        f"/api/v1/conversations/{conv['id']}/messages",
        json={"role": "assistant", "content": "hi"},
        headers=headers,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_list_messages_in_chronological_order(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    import asyncio

    user = test_user_with_tokens["user"]
    page, _ = await create_page_with_dashboard(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])
    conv = await make_conversation(async_client, page.id, headers)

    contents = ["first", "second", "third"]
    for c in contents:
        await async_client.post(
            f"/api/v1/conversations/{conv['id']}/messages",
            json={"role": "user", "content": c},
            headers=headers,
        )
        await asyncio.sleep(0.01)

    r = await async_client.get(
        f"/api/v1/conversations/{conv['id']}/messages", headers=headers
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["content"] for i in items] == contents


# ─── A3 & A7: pin assistant messages ──────────────────────────────────────


@pytest.mark.asyncio
async def test_pin_assistant_message_creates_widget(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    page, dash = await create_page_with_dashboard(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])
    conv = await make_conversation(async_client, page.id, headers)
    msg = await make_assistant_message(db_session, conv["id"], content="answer!")

    r = await async_client.post(
        f"/api/v1/messages/{msg.id}/pin",
        json={"dashboard_id": str(dash.id), "widget_type": "insight"},
        headers=headers,
    )
    assert r.status_code == 201
    data = r.json()
    assert data["pinned_message_id"] == str(msg.id)
    assert data["conversation_id"] == conv["id"]


@pytest.mark.asyncio
async def test_pin_user_message_rejected(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    page, dash = await create_page_with_dashboard(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])
    conv = await make_conversation(async_client, page.id, headers)

    r1 = await async_client.post(
        f"/api/v1/conversations/{conv['id']}/messages",
        json={"role": "user", "content": "question?"},
        headers=headers,
    )
    user_msg_id = r1.json()["id"]

    r2 = await async_client.post(
        f"/api/v1/messages/{user_msg_id}/pin",
        json={"dashboard_id": str(dash.id)},
        headers=headers,
    )
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_pin_same_message_twice_returns_same_widget(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    """A11 — concurrent pin should resolve to one widget.

    We simulate the race with two sequential calls; the second must
    return the same widget_id, not create a second row.
    """
    user = test_user_with_tokens["user"]
    page, dash = await create_page_with_dashboard(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])
    conv = await make_conversation(async_client, page.id, headers)
    msg = await make_assistant_message(db_session, conv["id"])

    r1 = await async_client.post(
        f"/api/v1/messages/{msg.id}/pin",
        json={"dashboard_id": str(dash.id)},
        headers=headers,
    )
    r2 = await async_client.post(
        f"/api/v1/messages/{msg.id}/pin",
        json={"dashboard_id": str(dash.id)},
        headers=headers,
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["widget_id"] == r2.json()["widget_id"]


@pytest.mark.asyncio
async def test_pin_two_different_messages_creates_two_widgets(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    """A7 — same thread, two different assistant messages, two widgets."""
    user = test_user_with_tokens["user"]
    page, dash = await create_page_with_dashboard(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])
    conv = await make_conversation(async_client, page.id, headers)
    msg_a = await make_assistant_message(db_session, conv["id"], content="A")
    msg_b = await make_assistant_message(db_session, conv["id"], content="B")

    r_a = await async_client.post(
        f"/api/v1/messages/{msg_a.id}/pin",
        json={"dashboard_id": str(dash.id)},
        headers=headers,
    )
    r_b = await async_client.post(
        f"/api/v1/messages/{msg_b.id}/pin",
        json={"dashboard_id": str(dash.id)},
        headers=headers,
    )
    assert r_a.json()["widget_id"] != r_b.json()["widget_id"]
    # Both widgets share the same conversation
    assert r_a.json()["conversation_id"] == r_b.json()["conversation_id"]


# ─── A6: fork ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fork_copies_messages_up_to_branch_point(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    import asyncio

    user = test_user_with_tokens["user"]
    page, _ = await create_page_with_dashboard(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])
    conv = await make_conversation(async_client, page.id, headers)

    created_ids = []
    for content in ["q1", "q2", "q3", "q4"]:
        r = await async_client.post(
            f"/api/v1/conversations/{conv['id']}/messages",
            json={"role": "user", "content": content},
            headers=headers,
        )
        created_ids.append(r.json()["id"])
        await asyncio.sleep(0.01)

    # Branch at the 2nd message — expect the forked thread to contain q1 + q2
    fork_r = await async_client.post(
        f"/api/v1/conversations/{conv['id']}/fork",
        json={"from_message_id": created_ids[1]},
        headers=headers,
    )
    assert fork_r.status_code == 201
    branch = fork_r.json()
    assert branch["id"] != conv["id"]
    assert branch["created_by"] == str(user.id)
    assert branch["space_id"] is None and branch["crew_id"] is None

    # List messages of the new branch — should have q1 and q2 only
    list_r = await async_client.get(
        f"/api/v1/conversations/{branch['id']}/messages", headers=headers
    )
    items = list_r.json()["items"]
    assert [m["content"] for m in items] == ["q1", "q2"]


@pytest.mark.asyncio
async def test_fork_with_foreign_message_id_returns_400(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    page, _ = await create_page_with_dashboard(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])

    conv_a = await make_conversation(async_client, page.id, headers)
    conv_b = await make_conversation(async_client, page.id, headers)

    r = await async_client.post(
        f"/api/v1/conversations/{conv_b['id']}/messages",
        json={"role": "user", "content": "in B"},
        headers=headers,
    )
    msg_in_b = r.json()["id"]

    fork_r = await async_client.post(
        f"/api/v1/conversations/{conv_a['id']}/fork",
        json={"from_message_id": msg_in_b},
        headers=headers,
    )
    assert fork_r.status_code == 400


# ─── RBAC ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_member_cannot_list_messages_in_crew_conversation(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    owner = test_user_with_tokens["user"]
    outsider = await create_user(db_session, "out@x.com")
    page, _ = await create_page_with_dashboard(db_session, owner.id)

    space = Space(name="S", created_by=owner.id)
    db_session.add(space)
    await db_session.commit()
    await db_session.refresh(space)
    db_session.add(SpaceMember(space_id=space.id, user_id=owner.id))
    crew = Crew(name="C", space_id=space.id, created_by=owner.id)
    db_session.add(crew)
    await db_session.commit()
    await db_session.refresh(crew)
    db_session.add(CrewMember(crew_id=crew.id, user_id=owner.id, role="owner"))
    await db_session.commit()

    owner_headers = get_auth_headers(test_user_with_tokens["access_token"])
    outsider_token = create_access_token({"sub": str(outsider.id)})
    outsider_headers = get_auth_headers(outsider_token)

    conv = await make_conversation(
        async_client, page.id, owner_headers,
        body={"space_id": str(space.id), "crew_id": str(crew.id)},
    )

    r = await async_client.get(
        f"/api/v1/conversations/{conv['id']}/messages", headers=outsider_headers
    )
    assert r.status_code == 404
