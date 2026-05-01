"""Tests for the periodic_sweep Celery worker.

Strategy: skip the Celery roundtrip and exercise the inner async
function directly with a patched ``AsyncSessionLocal`` that yields the
test session. This mirrors the pattern other worker tests use
(test_ai_worker_unit.py).
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest

from src.models.agent import Agent, AgentScope, AgentStatus
from src.models.space import SpaceMember


@pytest.mark.asyncio
async def test_sweep_pauses_orphan_when_creator_left(db_session, monkeypatch):
    """Creator has no SpaceMember row for the agent's space → orphan,
    must be paused by the sweep."""

    @asynccontextmanager
    async def _fake_session():
        yield db_session

    # Patch the session factory the worker uses.
    monkeypatch.setattr(
        "src.config.database.AsyncSessionLocal",
        lambda: _fake_session(),
    )

    creator = uuid.uuid4()
    space = uuid.uuid4()

    agent = Agent(
        id=uuid.uuid4(),
        name="orphan",
        archetype="custom",
        scope=AgentScope.SPACE.value,
        scope_id=str(space),
        status=AgentStatus.ACTIVE.value,
        monitor_type="question",
        focus="t",
        frequency="daily",
        connection_ids=[],
        created_by=creator,
        identity_type="user",
    )
    db_session.add(agent)
    await db_session.commit()

    # Import lazily — the worker module imports celery_app on import.
    from src.workers.agent_revocation_worker import _sweep_async

    result = await _sweep_async()
    await db_session.refresh(agent)

    assert result["paused"] == 1
    assert agent.status == AgentStatus.PAUSED.value


@pytest.mark.asyncio
async def test_sweep_keeps_agent_when_creator_still_member(db_session, monkeypatch):
    @asynccontextmanager
    async def _fake_session():
        yield db_session

    monkeypatch.setattr(
        "src.config.database.AsyncSessionLocal",
        lambda: _fake_session(),
    )

    creator = uuid.uuid4()
    space = uuid.uuid4()

    db_session.add(SpaceMember(space_id=space, user_id=creator, role="editor"))
    agent = Agent(
        id=uuid.uuid4(),
        name="ok",
        archetype="custom",
        scope=AgentScope.SPACE.value,
        scope_id=str(space),
        status=AgentStatus.ACTIVE.value,
        monitor_type="question",
        focus="t",
        frequency="daily",
        connection_ids=[],
        created_by=creator,
        identity_type="user",
    )
    db_session.add(agent)
    await db_session.commit()

    from src.workers.agent_revocation_worker import _sweep_async

    result = await _sweep_async()
    await db_session.refresh(agent)

    assert result["paused"] == 0
    assert agent.status == AgentStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_sweep_idempotent(db_session, monkeypatch):
    """Running the sweep twice in a row paus no extras the second time."""

    @asynccontextmanager
    async def _fake_session():
        yield db_session

    monkeypatch.setattr(
        "src.config.database.AsyncSessionLocal",
        lambda: _fake_session(),
    )

    creator = uuid.uuid4()
    agent = Agent(
        id=uuid.uuid4(),
        name="orphan",
        archetype="custom",
        scope=AgentScope.SPACE.value,
        scope_id=str(uuid.uuid4()),
        status=AgentStatus.ACTIVE.value,
        monitor_type="question",
        focus="t",
        frequency="daily",
        connection_ids=[],
        created_by=creator,
        identity_type="user",
    )
    db_session.add(agent)
    await db_session.commit()

    from src.workers.agent_revocation_worker import _sweep_async

    first = await _sweep_async()
    second = await _sweep_async()

    assert first["paused"] == 1
    assert second["paused"] == 0


def test_celery_task_is_registered():
    """The @celery_app.task decorator should register the task by name —
    operators can introspect via celery.control.inspect.registered()."""
    from src.workers.celery_app import celery_app

    name = "src.workers.agent_revocation_worker.sweep_orphan_agents"
    # Force-import the worker module so the decorator runs.
    from src.workers import agent_revocation_worker  # noqa: F401

    assert name in celery_app.tasks


def test_beat_schedule_includes_sweep():
    """beat_schedule must contain an entry firing the sweep at 15min."""
    from datetime import timedelta

    from src.workers.celery_app import celery_app

    schedule = getattr(celery_app.conf, "beat_schedule", {}) or {}
    entry = schedule.get("sweep-orphan-agents")
    assert entry is not None, f"expected sweep-orphan-agents in beat schedule, got {list(schedule)}"
    assert entry["task"] == "src.workers.agent_revocation_worker.sweep_orphan_agents"
    assert entry["schedule"] == timedelta(minutes=15)
