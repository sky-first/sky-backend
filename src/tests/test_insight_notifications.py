"""Tests for insight-run notification emission — Phase 3.3.

The worker emits up to two notifications per successful run. We test
the emitter in isolation (mocking the Redis / AI side) so these tests
stay fast on SQLite.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.agent import Agent, AgentFrequency, AgentScope
from src.models.notification import Notification, NotificationType
from src.workers.insight_agent_worker import _emit_insight_notifications


async def _make_agent(db: AsyncSession, *, user_id, widget_id=None) -> Agent:
    agent = Agent(
        name="Revenue watcher",
        scope=AgentScope.PERSONAL,
        scope_id=str(uuid.uuid4()),
        scope_name="self",
        frequency=AgentFrequency.DAILY,
        focus="Revenue",
        created_by=user_id,
        widget_id=widget_id,
    )
    db.add(agent)
    await db.flush()
    return agent


# ─── N1 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_material_run_emits_both_result_and_material(
    test_user, db_session: AsyncSession
):
    widget_id = uuid.uuid4()
    agent = await _make_agent(
        db_session, user_id=test_user["user"].id, widget_id=widget_id
    )
    await db_session.commit()

    await _emit_insight_notifications(
        db_session,
        agent=agent,
        run_id=uuid.uuid4(),
        delta_kind="material",
        delta_summary="Revenue dropped 8% vs. last week",
    )
    await db_session.commit()

    rows = (
        await db_session.execute(select(Notification).order_by(Notification.type))
    ).scalars().all()
    types = sorted(r.type for r in rows)
    assert types == [
        NotificationType.INSIGHT_AGENT_MATERIAL.value,
        NotificationType.INSIGHT_AGENT_RESULT.value,
    ]
    # Both should carry the widget deep-link
    for r in rows:
        assert r.deep_link == f"/dashboard?insight={widget_id}"
        assert "8%" in (r.description or "")


# ─── N2 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_trivial_run_emits_result_only(
    test_user, db_session: AsyncSession
):
    agent = await _make_agent(db_session, user_id=test_user["user"].id)
    await db_session.commit()

    await _emit_insight_notifications(
        db_session,
        agent=agent,
        run_id=uuid.uuid4(),
        delta_kind="trivial",
        delta_summary=None,
    )
    await db_session.commit()

    rows = (await db_session.execute(select(Notification))).scalars().all()
    assert len(rows) == 1
    assert rows[0].type == NotificationType.INSIGHT_AGENT_RESULT.value


# ─── N3 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_no_widget_id_produces_null_deep_link(
    test_user, db_session: AsyncSession
):
    """An agent without a bound widget still produces a feed entry; the
    deep_link is just null (the UI falls back to the default activity
    view)."""
    agent = await _make_agent(db_session, user_id=test_user["user"].id, widget_id=None)
    await db_session.commit()

    await _emit_insight_notifications(
        db_session,
        agent=agent,
        run_id=uuid.uuid4(),
        delta_kind="first_run",
        delta_summary="Initial baseline captured",
    )
    await db_session.commit()

    rows = (await db_session.execute(select(Notification))).scalars().all()
    assert len(rows) == 1
    assert rows[0].deep_link is None


# ─── N4 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sp_owned_agent_emits_nothing(
    test_user, db_session: AsyncSession
):
    """Agents owned by a service principal (created_by=None) have no
    human to notify here — they'd fan out to crew admins later."""
    agent = Agent(
        name="SP-owned",
        scope=AgentScope.CREW,
        scope_id=str(uuid.uuid4()),
        scope_name="crew",
        frequency=AgentFrequency.DAILY,
        focus="?",
        created_by=None,
    )
    db_session.add(agent)
    await db_session.flush()

    await _emit_insight_notifications(
        db_session,
        agent=agent,
        run_id=uuid.uuid4(),
        delta_kind="material",
        delta_summary="anything",
    )
    await db_session.commit()

    rows = (await db_session.execute(select(Notification))).scalars().all()
    assert rows == []


# ─── N5 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_notification_category_routes_to_agents(
    test_user, db_session: AsyncSession
):
    """The new types must be in NOTIFICATION_CATEGORY so the mute
    infrastructure treats them as 'agents' — otherwise muting the
    agents category wouldn't silence insight reruns."""
    from src.models.notification import NOTIFICATION_CATEGORY

    assert NOTIFICATION_CATEGORY["insight_agent_material"] == "agents"
    assert NOTIFICATION_CATEGORY["insight_agent_result"] == "agents"
