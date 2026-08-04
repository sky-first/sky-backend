"""Tests for the schedule_agents Celery worker.

Regression cover for the production incident where 50 agents sat at
status='active' with next_execution_at=NULL and were never scheduled:
`NULL <= now` is NULL in SQL, not TRUE, so the plain comparison filtered
them out silently while the UI kept reporting them as active.

Strategy: skip the Celery roundtrip and exercise ``_schedule_agents_async``
directly with a patched ``AsyncSessionLocal`` — same pattern as
test_agent_revocation_worker.py.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

from src.models.agent import Agent, AgentScope, AgentStatus


def _aware(dt):
    """SQLite (the test DB) drops tzinfo on round-trip; Postgres keeps it.
    Normalise so assertions work on both."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _agent(*, next_execution_at, frequency="daily", status=AgentStatus.ACTIVE.value,
           monitor_type="question", name="a"):
    return Agent(
        id=uuid.uuid4(),
        name=name,
        archetype="custom",
        scope=AgentScope.SPACE.value,
        scope_id=str(uuid.uuid4()),
        status=status,
        monitor_type=monitor_type,
        focus="t",
        frequency=frequency,
        connection_ids=[],
        created_by=uuid.uuid4(),
        identity_type="user",
        next_execution_at=next_execution_at,
    )


@pytest.fixture
def _patched_session(db_session, monkeypatch):
    @asynccontextmanager
    async def _fake_session():
        yield db_session

    monkeypatch.setattr(
        "src.config.database.AsyncSessionLocal",
        lambda: _fake_session(),
    )
    return db_session


@pytest.fixture
def _captured_enqueues(monkeypatch):
    """Capture execute_agent.delay calls instead of hitting the broker."""
    calls: list[str] = []
    from src.workers import agent_worker

    monkeypatch.setattr(
        agent_worker.execute_agent, "delay", lambda agent_id: calls.append(agent_id)
    )
    return calls


@pytest.mark.asyncio
async def test_due_agent_is_enqueued(_patched_session, _captured_enqueues):
    """Baseline: a past-due agent still gets picked up."""
    db = _patched_session
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    agent = _agent(next_execution_at=past)
    db.add(agent)
    await db.commit()

    from src.workers.agent_worker import _schedule_agents_async

    enqueued, healed = await _schedule_agents_async()

    assert enqueued == 1
    assert healed == 0
    assert _captured_enqueues == [str(agent.id)]


@pytest.mark.asyncio
async def test_future_agent_is_not_enqueued(_patched_session, _captured_enqueues):
    db = _patched_session
    future = datetime.now(timezone.utc) + timedelta(hours=5)
    db.add(_agent(next_execution_at=future))
    await db.commit()

    from src.workers.agent_worker import _schedule_agents_async

    enqueued, healed = await _schedule_agents_async()

    assert (enqueued, healed) == (0, 0)
    assert _captured_enqueues == []


@pytest.mark.asyncio
async def test_null_schedule_is_healed_not_run(_patched_session, _captured_enqueues):
    """The regression: an active agent with a NULL schedule must be
    rescheduled rather than ignored — and must NOT fire immediately."""
    db = _patched_session
    agent = _agent(next_execution_at=None)
    db.add(agent)
    await db.commit()

    from src.workers.agent_worker import _schedule_agents_async

    enqueued, healed = await _schedule_agents_async()

    assert healed == 1
    assert enqueued == 0, "a recovered agent must not run in the same pass"
    assert _captured_enqueues == []

    await db.refresh(agent)
    assert agent.next_execution_at is not None
    assert _aware(agent.next_execution_at) > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_healed_agents_are_staggered(_patched_session, _captured_enqueues):
    """Recovering many at once must not schedule them all for the same
    instant — that would stampede the AI service and spike LLM spend."""
    db = _patched_session
    agents = [_agent(next_execution_at=None, name=f"a{i}") for i in range(10)]
    for a in agents:
        db.add(a)
    await db.commit()

    from src.workers.agent_worker import _schedule_agents_async

    _, healed = await _schedule_agents_async()
    assert healed == 10

    for a in agents:
        await db.refresh(a)
    stamps = {a.next_execution_at for a in agents}
    assert len(stamps) == 10, "each recovered agent needs its own slot"

    # All land inside the frequency window (24h for daily), none in the past.
    now = datetime.now(timezone.utc)
    for a in agents:
        assert now < _aware(a.next_execution_at) <= now + timedelta(hours=24)


@pytest.mark.asyncio
async def test_paused_agent_with_null_schedule_is_left_alone(
    _patched_session, _captured_enqueues
):
    """Healing must not resurrect agents a human deliberately paused."""
    db = _patched_session
    agent = _agent(next_execution_at=None, status="paused")
    db.add(agent)
    await db.commit()

    from src.workers.agent_worker import _schedule_agents_async

    enqueued, healed = await _schedule_agents_async()

    assert (enqueued, healed) == (0, 0)
    await db.refresh(agent)
    assert agent.next_execution_at is None


@pytest.mark.asyncio
async def test_insight_agents_are_skipped(_patched_session, _captured_enqueues):
    """Insight-mode agents belong to insight_agent_worker — the legacy
    scheduler must not touch them, NULL schedule or not."""
    db = _patched_session
    agent = _agent(next_execution_at=None, monitor_type="insight")
    db.add(agent)
    await db.commit()

    from src.workers.agent_worker import _schedule_agents_async

    enqueued, healed = await _schedule_agents_async()

    assert (enqueued, healed) == (0, 0)
    await db.refresh(agent)
    assert agent.next_execution_at is None
