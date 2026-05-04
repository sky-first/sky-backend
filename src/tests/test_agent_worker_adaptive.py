"""agent_worker — adaptive scheduling unit tests.

Covers `_adaptive_interval_hours`: the leading-streak detector that
multiplies the next-run interval when recent runs are all empty. The
worker integration (next_execution_at) is exercised via the existing
end-to-end agent tests; this file only verifies the math.

Behaviour matrix:
  • Streak below threshold → base hours, untouched
  • Threshold streak → 2× base
  • Threshold + 1 → 4× base
  • Cap at 7 days (168h) regardless of streak length
  • Any non-zero in the leading window resets to base
  • base_hours <= 0 short-circuits (defensive)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import get_password_hash
from src.models.agent import Agent, AgentExecution
from src.repositories.user import UserRepository
from src.workers.agent_worker import (
    ADAPTIVE_BACKOFF_MAX_HOURS,
    _adaptive_interval_hours,
)


async def _user(db):
    return await UserRepository(db).create(
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=get_password_hash("Test@2024!"),
        name="Adaptive Test",
        role="member",
    )


async def _agent(db, *, owner) -> Agent:
    # scope_id and scope_name became NOT NULL after the agent-scope
    # migration; for personal-scope test fixtures we just point at the
    # owner's own UUID so the row is well-formed.
    a = Agent(
        id=uuid.uuid4(),
        name=f"agent-{uuid.uuid4().hex[:6]}",
        scope="personal",
        # scope_id is String(255); SQLite (test backend) won't bind a raw UUID.
        scope_id=str(owner.id),
        scope_name="Personal",
        status="active",
        frequency="daily",
        focus="Test focus",
        connection_ids=[],
        created_by=owner.id,
    )
    db.add(a)
    await db.flush()
    return a


async def _seed_runs(
    db: AsyncSession,
    *,
    agent_id,
    findings_counts: list[int],
    spacing_minutes: int = 60,
):
    """Insert AgentExecution rows ordered oldest→newest.
    `findings_counts` is read in that order; the most recent entry
    is `findings_counts[-1]`.

    Note on the helper contract: `_adaptive_interval_hours` drops
    `history[0]` (the newest row) on the assumption that SQLAlchemy
    autoflush has already persisted the current run. In tests we don't
    flush a "current" row, so callers that want streak == N should
    seed N rows where the newest is a placeholder that the helper
    will discard, plus pass `current_findings` separately.
    """
    base = datetime.now(timezone.utc) - timedelta(
        minutes=spacing_minutes * len(findings_counts)
    )
    for i, count in enumerate(findings_counts):
        ex = AgentExecution(
            id=uuid.uuid4(),
            agent_id=agent_id,
            status="completed",
            findings_count=count,
            started_at=base + timedelta(minutes=spacing_minutes * i),
            finished_at=base + timedelta(minutes=spacing_minutes * i + 1),
        )
        db.add(ex)
    await db.flush()


@pytest.mark.asyncio
async def test_streak_below_threshold_stays_at_base(db_session):
    user = await _user(db_session)
    agent = await _agent(db_session, owner=user)
    # 1 seeded row + current=0; helper drops the newest seed row →
    # counts = [0_current] → streak=1 → below threshold → base.
    await _seed_runs(db_session, agent_id=agent.id, findings_counts=[0])
    hours = await _adaptive_interval_hours(
        db_session, agent.id, base_hours=24, current_findings=0
    )
    assert hours == 24


@pytest.mark.asyncio
async def test_threshold_doubles_interval(db_session):
    user = await _user(db_session)
    agent = await _agent(db_session, owner=user)
    # 3 seeded rows + current=0; helper drops the newest seed row
    # (autoflush placeholder) → counts = [0_current, 0, 0] → streak=3
    # → 2× base.
    await _seed_runs(db_session, agent_id=agent.id, findings_counts=[0, 0, 0])
    hours = await _adaptive_interval_hours(
        db_session, agent.id, base_hours=24, current_findings=0
    )
    assert hours == 48


@pytest.mark.asyncio
async def test_one_extra_empty_quadruples_interval(db_session):
    user = await _user(db_session)
    agent = await _agent(db_session, owner=user)
    # 4 seeded rows + current=0; helper drops the newest seed row →
    # counts = [0_current, 0, 0, 0] → streak=4 → 4× base.
    await _seed_runs(db_session, agent_id=agent.id, findings_counts=[0, 0, 0, 0])
    hours = await _adaptive_interval_hours(
        db_session, agent.id, base_hours=24, current_findings=0
    )
    assert hours == 96


@pytest.mark.asyncio
async def test_caps_at_seven_days(db_session):
    user = await _user(db_session)
    agent = await _agent(db_session, owner=user)
    # Long streak — multiplier would blow past 7 days; helper must cap.
    await _seed_runs(db_session, agent_id=agent.id, findings_counts=[0] * 15)
    hours = await _adaptive_interval_hours(
        db_session, agent.id, base_hours=24, current_findings=0
    )
    assert hours == ADAPTIVE_BACKOFF_MAX_HOURS  # 168


@pytest.mark.asyncio
async def test_finding_resets_to_base(db_session):
    user = await _user(db_session)
    agent = await _agent(db_session, owner=user)
    # Long quiet history but the current run actually found something.
    await _seed_runs(db_session, agent_id=agent.id, findings_counts=[0] * 8)
    hours = await _adaptive_interval_hours(
        db_session, agent.id, base_hours=24, current_findings=2
    )
    assert hours == 24


@pytest.mark.asyncio
async def test_finding_in_history_resets(db_session):
    user = await _user(db_session)
    agent = await _agent(db_session, owner=user)
    # Pattern (oldest→newest): 0, 5, 0, 0, 0. After the helper drops
    # the newest seed row (autoflush placeholder), counts become
    # [0_current, 0, 0, 5, 0]. Streak stops at the third zero where
    # the 5 breaks it — exactly threshold → 2× base.
    await _seed_runs(db_session, agent_id=agent.id, findings_counts=[0, 5, 0, 0, 0])
    hours = await _adaptive_interval_hours(
        db_session, agent.id, base_hours=24, current_findings=0
    )
    assert hours == 48


@pytest.mark.asyncio
async def test_zero_base_hours_short_circuits(db_session):
    """Defensive: don't try to scale a degenerate interval."""
    user = await _user(db_session)
    agent = await _agent(db_session, owner=user)
    await _seed_runs(db_session, agent_id=agent.id, findings_counts=[0] * 5)
    hours = await _adaptive_interval_hours(
        db_session, agent.id, base_hours=0, current_findings=0
    )
    assert hours == 0
