"""Tests for insight-mode agents — Phase 1 iteration 1.5.

Use cases covered (docs/agent-and-ai-master-plan.md §10 B):
  B1   Create insight agent — identity resolves from page scope
  B6   Update schedule recomputes next_execution_at
  B7   Pause clears next_execution_at
  B8   Resume sets next_execution_at to now
  B9   Delete moves status to 'ended' (row preserved for audit)
  B10  Run-now bypasses schedule — next_execution_at = now

Plus negative / RBAC paths:
  - Non-creator cannot mutate
  - Creating an agent for a widget on a crew page resolves to sp-crew
  - Creating for a space page resolves to sp-space
  - Ended agent cannot be paused/resumed/run
"""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token, get_password_hash
from src.models.agent import Agent
from src.models.crew import Crew, CrewMember
from src.models.widget import Widget
from src.models.page import Page
from src.models.service_principal import ServicePrincipal
from src.models.space import Space, SpaceMember
from src.repositories.user import UserRepository


def get_auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


async def _make_user(db: AsyncSession, email: str):
    repo = UserRepository(db)
    user = await repo.create(
        email=email,
        password_hash=get_password_hash("pw"),
        name=email.split("@")[0],
        role="user",
    )
    await db.commit()
    return user


async def _seed_personal_page_with_widget(db: AsyncSession, user_id):
    page = Page(name="P", type="personal", color="#3b82f6", owner_id=user_id)
    db.add(page)
    await db.commit()
    await db.refresh(page)
    widget = Widget(
        page_id=page.id,
        type="insight",
        title="Revenue YoY",
        position={"x": 0, "y": 0},
        size={"width": 400, "height": 300},
        data={},
    )
    db.add(widget)
    await db.commit()
    await db.refresh(widget)
    return page, widget


async def _seed_space_page_with_widget(db: AsyncSession, user_id):
    space = Space(name="S", created_by=user_id)
    db.add(space)
    await db.commit()
    await db.refresh(space)
    db.add(SpaceMember(space_id=space.id, user_id=user_id))
    sp = ServicePrincipal(space_id=space.id, name=f"sa-space-{str(space.id)[:8]}")
    db.add(sp)
    await db.commit()
    await db.refresh(sp)

    page = Page(
        name="P", type="team", color="#3b82f6", owner_id=user_id, space_id=space.id
    )
    db.add(page)
    await db.commit()
    await db.refresh(page)
    widget = Widget(
        page_id=page.id, type="insight", title="Space KPI",
        position={"x": 0, "y": 0}, size={"width": 400, "height": 300}, data={},
    )
    db.add(widget)
    await db.commit()
    await db.refresh(widget)
    return page, widget, space, sp


async def _seed_crew_page_with_widget(db: AsyncSession, user_id):
    space = Space(name="S", created_by=user_id)
    db.add(space)
    await db.commit()
    await db.refresh(space)
    db.add(SpaceMember(space_id=space.id, user_id=user_id))
    await db.commit()
    crew = Crew(name="C", space_id=space.id, created_by=user_id)
    db.add(crew)
    await db.commit()
    await db.refresh(crew)
    db.add(CrewMember(crew_id=crew.id, user_id=user_id, role="owner"))
    sp = ServicePrincipal(crew_id=crew.id, name=f"sa-crew-{str(crew.id)[:8]}")
    db.add(sp)
    await db.commit()
    await db.refresh(sp)

    page = Page(
        name="P", type="team", color="#3b82f6",
        owner_id=user_id, space_id=space.id, crew_id=crew.id,
    )
    db.add(page)
    await db.commit()
    await db.refresh(page)
    widget = Widget(
        page_id=page.id, type="insight", title="Crew KPI",
        position={"x": 0, "y": 0}, size={"width": 400, "height": 300}, data={},
    )
    db.add(widget)
    await db.commit()
    await db.refresh(widget)
    return page, widget, crew, sp


# ─── B1: create ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_insight_agent_for_personal_widget(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    _, widget = await _seed_personal_page_with_widget(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])

    r = await async_client.post(
        "/api/v1/agents/insight",
        json={
            "widget_id": str(widget.id),
            "schedule": {"interval_value": 1, "interval_unit": "day"},
            "notify_on_change": True,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["monitor_type"] == "insight"
    assert data["widget_id"] == str(widget.id)
    assert data["identity_type"] == "user"
    assert data["service_principal_id"] is None
    assert data["status"] == "active"
    assert data["schedule_jsonb"]["interval_value"] == 1
    assert data["schedule_jsonb"]["interval_unit"] == "day"
    assert data["next_execution_at"] is not None
    assert data["consecutive_failures"] == 0
    assert data["notify_on_change"] is True


@pytest.mark.asyncio
async def test_create_insight_agent_on_space_page_uses_space_sp(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    _, widget, space, sp = await _seed_space_page_with_widget(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])

    r = await async_client.post(
        "/api/v1/agents/insight",
        json={
            "widget_id": str(widget.id),
            "schedule": {"interval_value": 6, "interval_unit": "hour"},
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["identity_type"] == "service_principal"
    assert data["service_principal_id"] == str(sp.id)
    assert data["scope"] == "space"
    assert data["scope_id"] == str(space.id)


@pytest.mark.asyncio
async def test_create_insight_agent_on_crew_page_uses_crew_sp(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    _, widget, crew, sp = await _seed_crew_page_with_widget(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])

    r = await async_client.post(
        "/api/v1/agents/insight",
        json={
            "widget_id": str(widget.id),
            "schedule": {"interval_value": 30, "interval_unit": "minute"},
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["identity_type"] == "service_principal"
    assert data["service_principal_id"] == str(sp.id)
    assert data["scope"] == "crew"
    assert data["scope_id"] == str(crew.id)


@pytest.mark.asyncio
async def test_create_with_unknown_widget_returns_404(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    headers = get_auth_headers(test_user_with_tokens["access_token"])
    r = await async_client.post(
        "/api/v1/agents/insight",
        json={
            "widget_id": str(uuid4()),
            "schedule": {"interval_value": 1, "interval_unit": "hour"},
        },
        headers=headers,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_schedule_rejects_zero_interval():
    from pydantic import ValidationError
    from src.schemas.insight_agent import AgentScheduleConfig

    with pytest.raises(ValidationError):
        AgentScheduleConfig(interval_value=0, interval_unit="minute")


# ─── B6: update ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_schedule_recomputes_next_execution_at(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    _, widget = await _seed_personal_page_with_widget(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])

    r = await async_client.post(
        "/api/v1/agents/insight",
        json={
            "widget_id": str(widget.id),
            "schedule": {"interval_value": 1, "interval_unit": "day"},
        },
        headers=headers,
    )
    agent_id = r.json()["id"]
    original_next = datetime.fromisoformat(r.json()["next_execution_at"])

    # Switch to 5 minutes — next run should now be ~5 min out, not ~1 day out
    import asyncio
    await asyncio.sleep(0.02)
    r2 = await async_client.put(
        f"/api/v1/agents/insight/{agent_id}",
        json={"schedule": {"interval_value": 5, "interval_unit": "minute"}},
        headers=headers,
    )
    assert r2.status_code == 200
    new_next = datetime.fromisoformat(r2.json()["next_execution_at"])
    # New next must be before the old one (minutes < day)
    assert new_next < original_next


# ─── B7/B8: pause / resume ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pause_clears_next_execution_and_resume_sets_it_to_now(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    _, widget = await _seed_personal_page_with_widget(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])

    r = await async_client.post(
        "/api/v1/agents/insight",
        json={
            "widget_id": str(widget.id),
            "schedule": {"interval_value": 1, "interval_unit": "hour"},
        },
        headers=headers,
    )
    agent_id = r.json()["id"]

    rp = await async_client.post(
        f"/api/v1/agents/insight/{agent_id}/pause", headers=headers
    )
    assert rp.status_code == 200
    assert rp.json()["status"] == "paused"
    assert rp.json()["next_execution_at"] is None

    rr = await async_client.post(
        f"/api/v1/agents/insight/{agent_id}/resume", headers=headers
    )
    assert rr.status_code == 200
    assert rr.json()["status"] == "active"
    # Next execution should now be near "now" — pick a generous window
    resumed_next = datetime.fromisoformat(rr.json()["next_execution_at"])
    delta = abs((datetime.utcnow() - resumed_next).total_seconds())
    assert delta < 5


# ─── B10: run-now ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_now_sets_next_execution_to_now(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    _, widget = await _seed_personal_page_with_widget(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])

    r = await async_client.post(
        "/api/v1/agents/insight",
        json={
            "widget_id": str(widget.id),
            "schedule": {"interval_value": 1, "interval_unit": "week"},
        },
        headers=headers,
    )
    agent_id = r.json()["id"]

    # Before run-now, next is ~1 week out
    before = datetime.fromisoformat(r.json()["next_execution_at"])
    assert (before - datetime.utcnow()).total_seconds() > 60

    rr = await async_client.post(
        f"/api/v1/agents/insight/{agent_id}/run-now", headers=headers
    )
    assert rr.status_code == 200
    after = datetime.fromisoformat(rr.json()["next_execution_at"])
    assert abs((datetime.utcnow() - after).total_seconds()) < 5


# ─── B9: delete ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_marks_ended_but_preserves_row(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    _, widget = await _seed_personal_page_with_widget(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])

    r = await async_client.post(
        "/api/v1/agents/insight",
        json={
            "widget_id": str(widget.id),
            "schedule": {"interval_value": 1, "interval_unit": "day"},
        },
        headers=headers,
    )
    agent_id = r.json()["id"]

    rd = await async_client.delete(
        f"/api/v1/agents/insight/{agent_id}", headers=headers
    )
    assert rd.status_code == 204

    # Row still exists, status='ended'
    from uuid import UUID as _UUID
    row = (
        await db_session.execute(
            select(Agent).where(Agent.id == _UUID(agent_id))
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.status == "ended"


# ─── Negative paths ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_creator_cannot_pause(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    _, widget = await _seed_personal_page_with_widget(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])

    r = await async_client.post(
        "/api/v1/agents/insight",
        json={
            "widget_id": str(widget.id),
            "schedule": {"interval_value": 1, "interval_unit": "day"},
        },
        headers=headers,
    )
    agent_id = r.json()["id"]

    other = await _make_user(db_session, "outsider@x.com")
    other_headers = get_auth_headers(create_access_token({"sub": str(other.id)}))

    r2 = await async_client.post(
        f"/api/v1/agents/insight/{agent_id}/pause", headers=other_headers
    )
    # Non-creator never sees the agent → 404 (existence hidden)
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_ended_agent_cannot_be_paused(
    async_client: AsyncClient, test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    _, widget = await _seed_personal_page_with_widget(db_session, user.id)
    headers = get_auth_headers(test_user_with_tokens["access_token"])

    r = await async_client.post(
        "/api/v1/agents/insight",
        json={
            "widget_id": str(widget.id),
            "schedule": {"interval_value": 1, "interval_unit": "day"},
        },
        headers=headers,
    )
    agent_id = r.json()["id"]

    await async_client.delete(f"/api/v1/agents/insight/{agent_id}", headers=headers)
    rp = await async_client.post(
        f"/api/v1/agents/insight/{agent_id}/pause", headers=headers
    )
    assert rp.status_code == 400
