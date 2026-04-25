"""Tests for the context-event emitter — Phase 2.2.

Coverage (see docs/agent-and-ai-master-plan.md §3.6):

  E8   Widget emits kind=widget and picks owner_user_id from created_by.

Phase 2.2b kinds — user / space / crew.

History
- E1–E5 + E9 personal-scope coverage removed in Phase 1a (2026-04-25)
  when the Strategy module was dropped.
- E6/E7 SignalEvent coverage removed in Phase 1b (2026-04-25) when the
  Events/Signals module was dropped.

The equivalent tests against the new Metric model land in Phase 2.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import context_events as ce
from src.models.dashboard import Widget


@pytest_asyncio.fixture
async def event_sink(db_session: AsyncSession):
    """Install session hooks + in-memory publish sink for this test."""
    from sqlalchemy.orm import Session as SyncSession

    captured: list[ce.ContextEvent] = []

    # Register on the base sync Session class — all AsyncSession-backed
    # sessions flush through an underlying sync Session instance of this
    # class (or a subclass), so one registration covers every test DB.
    ce._install_session_hooks(SyncSession)
    ce._register_default_mappings()
    ce.set_publisher(lambda evts: captured.extend(evts))
    try:
        yield captured
    finally:
        ce.set_publisher(None)
        captured.clear()


# ─── E8 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_widget_emits_widget_kind(
    db_session: AsyncSession, event_sink: list[ce.ContextEvent]
):
    from src.models.dashboard import Dashboard

    owner = uuid.uuid4()
    dashboard = Dashboard(name="Test", page_id=uuid.uuid4())
    db_session.add(dashboard)
    await db_session.flush()
    event_sink.clear()  # dashboard itself doesn't emit (not mapped)

    w = Widget(
        title="Revenue chart",
        type="chart",
        dashboard_id=dashboard.id,
        position={"x": 0, "y": 0},
        size={"width": 4, "height": 3},
        config={"chart_type": "line"},
        created_by=owner,
    )
    db_session.add(w)
    await db_session.commit()

    widget_events = [e for e in event_sink if e.kind == "widget"]
    assert len(widget_events) == 1
    assert widget_events[0].owner_user_id == str(owner)


# ─── Phase 2.2b kinds ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_user_insert_emits_user_kind_with_public_visibility(
    db_session: AsyncSession, event_sink: list[ce.ContextEvent]
):
    from src.core.security import get_password_hash
    from src.models.user import User

    user = User(
        email="paulo@sky.com",
        name="Paulo",
        password_hash=get_password_hash("x"),
        role="admin",
    )
    db_session.add(user)
    await db_session.commit()

    user_events = [e for e in event_sink if e.kind == "user"]
    assert len(user_events) == 1
    assert user_events[0].visibility == "public"
    assert user_events[0].source_table == "users"


@pytest.mark.asyncio
async def test_space_insert_emits_space_kind(
    db_session: AsyncSession, event_sink: list[ce.ContextEvent]
):
    from src.models.space import Space

    sp = Space(name="NovaTech", created_by=uuid.uuid4())
    db_session.add(sp)
    await db_session.commit()

    kinds = [e.kind for e in event_sink]
    assert "space" in kinds


@pytest.mark.asyncio
async def test_crew_insert_emits_crew_kind(
    db_session: AsyncSession, event_sink: list[ce.ContextEvent]
):
    from src.models.crew import Crew
    from src.models.space import Space

    sp = Space(name="S1", created_by=uuid.uuid4())
    db_session.add(sp)
    await db_session.flush()
    event_sink.clear()

    crew = Crew(name="Finance", space_id=sp.id, created_by=uuid.uuid4())
    db_session.add(crew)
    await db_session.commit()

    kinds = [e.kind for e in event_sink]
    assert "crew" in kinds
