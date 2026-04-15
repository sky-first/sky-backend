"""Tests for the context-event emitter — Phase 2.2.

Coverage (see docs/agent-and-ai-master-plan.md §3.6):

  E1   Inserting a Strategy goal emits one upsert event (kind=goal),
       with the scope (space_id) copied over verbatim.
  E2   Updating a goal emits another upsert.
  E3   Deleting via ORM .delete() emits action=delete.
  E4   Rollback suppresses pending events.
  E5   Multiple inserts in one commit are published together.
  E6   SignalEvent with category=EXTERNAL produces kind=event_external.
  E7   SignalEvent with category=TRENDS produces kind=event_trend.
  E8   Widget emits kind=widget and picks owner_user_id from created_by.
  E9   Emitter is tolerant of missing space/crew on personal-scope rows.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import context_events as ce
from src.models.dashboard import Widget
from src.models.signal_event import SignalCategory, SignalConfidence, SignalEvent, SignalNature
from src.models.strategy import StrategicObjective, StrategyOKR


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


# ─── E1 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_inserting_goal_emits_upsert_with_scope(
    db_session: AsyncSession, event_sink: list[ce.ContextEvent]
):
    space_id = uuid.uuid4()
    goal = StrategicObjective(
        type="corporate",
        title="Increase ARR by 20%",
        description="...",
        status="active",
        space_id=space_id,
    )
    db_session.add(goal)
    await db_session.commit()

    assert len(event_sink) == 1
    evt = event_sink[0]
    assert evt.action == "upsert"
    assert evt.kind == "goal"
    assert evt.source_table == "strategic_objectives"
    assert evt.source_id == str(goal.id)
    assert evt.space_id == str(space_id)


# ─── E2 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_updating_goal_emits_second_upsert(
    db_session: AsyncSession, event_sink: list[ce.ContextEvent]
):
    goal = StrategicObjective(type="corporate", title="A", description="...", status="active")
    db_session.add(goal)
    await db_session.commit()
    event_sink.clear()

    goal.title = "B"
    await db_session.commit()

    assert len(event_sink) == 1
    assert event_sink[0].action == "upsert"
    assert event_sink[0].source_id == str(goal.id)


# ─── E3 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_deleting_goal_emits_delete(
    db_session: AsyncSession, event_sink: list[ce.ContextEvent]
):
    goal = StrategicObjective(type="corporate", title="Doomed", description="...", status="active")
    db_session.add(goal)
    await db_session.commit()
    event_sink.clear()

    await db_session.delete(goal)
    await db_session.commit()

    assert len(event_sink) == 1
    assert event_sink[0].action == "delete"
    assert event_sink[0].kind == "goal"


# ─── E4 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_rollback_suppresses_events(
    db_session: AsyncSession, event_sink: list[ce.ContextEvent]
):
    goal = StrategicObjective(type="corporate", title="Ephemeral", description="...", status="active")
    db_session.add(goal)
    await db_session.flush()
    await db_session.rollback()

    assert event_sink == []


# ─── E5 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_batch_in_one_commit_emits_all(
    db_session: AsyncSession, event_sink: list[ce.ContextEvent]
):
    g1 = StrategicObjective(type="corporate", title="G1", description="", status="active")
    g2 = StrategicObjective(type="corporate", title="G2", description="", status="active")
    db_session.add_all([g1, g2])
    await db_session.flush()
    # OKR requires objective_id (not null FK), so attach to g1.
    okr = StrategyOKR(objective_id=g1.id, title="OKR1")
    db_session.add(okr)
    await db_session.commit()

    kinds = sorted(e.kind for e in event_sink)
    assert kinds == ["goal", "goal", "okr"]


# ─── E6 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_signal_event_external_kind(
    db_session: AsyncSession, event_sink: list[ce.ContextEvent]
):
    ev = SignalEvent(
        category=SignalCategory.EXTERNAL,
        sub_type="market_shift",
        nature=SignalNature.EVENT,
        confidence=SignalConfidence.HIGH,
        description="USD surge",
    )
    db_session.add(ev)
    await db_session.commit()

    assert len(event_sink) == 1
    assert event_sink[0].kind == "event_external"


# ─── E7 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_signal_event_trend_kind(
    db_session: AsyncSession, event_sink: list[ce.ContextEvent]
):
    ev = SignalEvent(
        category=SignalCategory.TRENDS,
        sub_type="ai_adoption",
        nature=SignalNature.SIGNAL,
        confidence=SignalConfidence.MEDIUM,
        description="LLM adoption up 40%",
    )
    db_session.add(ev)
    await db_session.commit()

    assert len(event_sink) == 1
    assert event_sink[0].kind == "event_trend"


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


# ─── E9 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_personal_scope_row_has_null_space_and_crew(
    db_session: AsyncSession, event_sink: list[ce.ContextEvent]
):
    goal = StrategicObjective(type="corporate", title="Personal", description="", status="active")
    db_session.add(goal)
    await db_session.commit()

    assert len(event_sink) == 1
    assert event_sink[0].space_id is None
    assert event_sink[0].crew_id is None
