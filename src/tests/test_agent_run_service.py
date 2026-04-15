"""Integration tests for AgentRunService — DB transitions + retry budget.

Covers master plan use cases D-series (agent_runs lifecycle):
  D1   Enqueue creates a queued run
  D4   report_success resets consecutive_failures + schedules next run
  D5   report_failure increments failures + schedules backoff
  D6   After 3 failures the agent moves to status='error'
  D8   Skipped runs (delta_kind=none) don't count as failures
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.agent_run_state import (
    FAILED,
    IllegalTransition,
    QUEUED,
    RUNNING,
    SKIPPED,
    SUCCEEDED,
)
from src.core.exceptions import NotFoundError
from src.core.security import get_password_hash
from src.models.agent import Agent, AgentExecution
from src.repositories.user import UserRepository
from src.services.agent_run_service import AgentRunService


async def _make_user(db: AsyncSession, email="rs@x.com"):
    repo = UserRepository(db)
    user = await repo.create(
        email=email,
        password_hash=get_password_hash("pw"),
        name="runner",
        role="user",
    )
    await db.commit()
    return user


async def _make_agent(
    db: AsyncSession,
    user_id,
    *,
    schedule={"interval_value": 1, "interval_unit": "hour"},
    ends_at=None,
):
    agent = Agent(
        name="t",
        archetype="custom",
        scope="personal",
        scope_id=str(user_id),
        status="active",
        frequency="hourly",
        monitor_type="insight",
        connection_ids=[],
        created_by=user_id,
        identity_type="user",
        schedule_jsonb=schedule,
        ends_at=ends_at,
        notify_on_change=True,
        delta_strategy="hash",
        consecutive_failures=0,
        next_execution_at=datetime.utcnow(),
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


# ─── enqueue ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enqueue_creates_queued_run(
    test_user_with_tokens, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    agent = await _make_agent(db_session, user.id)
    service = AgentRunService(db_session)

    run = await service.enqueue(agent.id)

    assert run.agent_id == agent.id
    assert run.status == QUEUED
    assert run.attributed_to_user_id == user.id
    assert run.started_at is not None


@pytest.mark.asyncio
async def test_enqueue_unknown_agent_raises(
    test_user_with_tokens, db_session: AsyncSession
):
    service = AgentRunService(db_session)
    with pytest.raises(NotFoundError):
        await service.enqueue(uuid4())


# ─── claim ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_claim_moves_queued_to_running(
    test_user_with_tokens, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    agent = await _make_agent(db_session, user.id)
    service = AgentRunService(db_session)
    run = await service.enqueue(agent.id)

    claimed = await service.claim(run.id)

    assert claimed.status == RUNNING


@pytest.mark.asyncio
async def test_claim_already_running_raises_illegal_transition(
    test_user_with_tokens, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    agent = await _make_agent(db_session, user.id)
    service = AgentRunService(db_session)
    run = await service.enqueue(agent.id)
    await service.claim(run.id)

    with pytest.raises(IllegalTransition):
        await service.claim(run.id)


# ─── report_success (D4) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_success_resets_failure_counter_and_schedules_next(
    test_user_with_tokens, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    agent = await _make_agent(
        db_session, user.id,
        schedule={"interval_value": 30, "interval_unit": "minute"},
    )
    # Pretend there were 2 prior failures
    agent.consecutive_failures = 2
    await db_session.commit()

    service = AgentRunService(db_session)
    run = await service.enqueue(agent.id)
    await service.claim(run.id)
    success = await service.report_success(
        run.id,
        result_hash="abc",
        delta_kind="first_run",
        llm_tokens_used=1000,
        llm_cost_usd=Decimal("0.0042"),
    )

    assert success.status == SUCCEEDED
    assert success.result_hash == "abc"
    assert success.delta_kind == "first_run"
    assert success.duration_ms is not None and success.duration_ms >= 0

    refreshed = (
        await db_session.execute(select(Agent).where(Agent.id == agent.id))
    ).scalar_one()
    assert refreshed.consecutive_failures == 0
    assert refreshed.last_execution_at is not None
    assert refreshed.next_execution_at is not None
    # 30 minutes out, ±2 minutes slack
    delta = refreshed.next_execution_at - datetime.utcnow()
    assert timedelta(minutes=28) <= delta <= timedelta(minutes=32)


# ─── Phase 2.10 context evidence writeback ───────────────────────────────


@pytest.mark.asyncio
async def test_report_success_persists_context_evidence(
    test_user_with_tokens, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    agent = await _make_agent(
        db_session, user.id,
        schedule={"interval_value": 1, "interval_unit": "hour"},
    )
    service = AgentRunService(db_session)
    run = await service.enqueue(agent.id)
    await service.claim(run.id)

    doc_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    success = await service.report_success(
        run.id,
        result_hash="ctx-trail",
        delta_kind="first_run",
        context_doc_ids=doc_ids,
        context_intent="strategy",
    )
    assert len(success.context_doc_ids) == 2
    assert success.context_intent == "strategy"


@pytest.mark.asyncio
async def test_report_success_without_context_keeps_defaults(
    test_user_with_tokens, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    agent = await _make_agent(
        db_session, user.id,
        schedule={"interval_value": 1, "interval_unit": "hour"},
    )
    service = AgentRunService(db_session)
    run = await service.enqueue(agent.id)
    await service.claim(run.id)
    success = await service.report_success(run.id, result_hash="no-ctx", delta_kind="first_run")
    assert list(success.context_doc_ids or []) == []
    assert success.context_intent is None


# ─── report_failure (D5, D6) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_failure_schedules_five_minute_retry(
    test_user_with_tokens, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    agent = await _make_agent(db_session, user.id)
    service = AgentRunService(db_session)
    run = await service.enqueue(agent.id)
    await service.claim(run.id)

    failed = await service.report_failure(run.id, error_message="boom")

    assert failed.status == FAILED
    assert failed.error_message == "boom"

    refreshed = (
        await db_session.execute(select(Agent).where(Agent.id == agent.id))
    ).scalar_one()
    assert refreshed.consecutive_failures == 1
    assert refreshed.status == "active"  # not yet exhausted
    # ~5 minutes out
    delta = refreshed.next_execution_at - datetime.utcnow()
    assert timedelta(minutes=4) <= delta <= timedelta(minutes=6)


@pytest.mark.asyncio
async def test_fourth_consecutive_failure_flips_agent_to_error(
    test_user_with_tokens, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    agent = await _make_agent(db_session, user.id)
    service = AgentRunService(db_session)

    for _ in range(4):
        run = await service.enqueue(agent.id)
        await service.claim(run.id)
        await service.report_failure(run.id, error_message="bad")

    refreshed = (
        await db_session.execute(select(Agent).where(Agent.id == agent.id))
    ).scalar_one()
    assert refreshed.consecutive_failures == 4
    assert refreshed.status == "error"
    assert refreshed.next_execution_at is None


# ─── report_skip (D8) ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skip_counts_as_success_for_failure_counter(
    test_user_with_tokens, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    agent = await _make_agent(db_session, user.id)
    agent.consecutive_failures = 2
    await db_session.commit()

    service = AgentRunService(db_session)
    run = await service.enqueue(agent.id)
    await service.claim(run.id)
    skipped = await service.report_skip(run.id)

    assert skipped.status == SKIPPED
    assert skipped.delta_kind == "none"

    refreshed = (
        await db_session.execute(select(Agent).where(Agent.id == agent.id))
    ).scalar_one()
    assert refreshed.consecutive_failures == 0
    assert refreshed.next_execution_at is not None


# ─── ends_at boundary ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_success_after_ends_at_stops_rescheduling(
    test_user_with_tokens, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    agent = await _make_agent(
        db_session, user.id,
        schedule={"interval_value": 1, "interval_unit": "hour"},
        ends_at=datetime.utcnow() + timedelta(minutes=5),  # ends before next run
    )
    service = AgentRunService(db_session)
    run = await service.enqueue(agent.id)
    await service.claim(run.id)
    await service.report_success(run.id, result_hash="x")

    refreshed = (
        await db_session.execute(select(Agent).where(Agent.id == agent.id))
    ).scalar_one()
    # Agent keeps running this time (we just landed) but there's no next run
    assert refreshed.next_execution_at is None


# ─── queue inspection ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_queued_returns_fifo(
    test_user_with_tokens, db_session: AsyncSession
):
    import asyncio
    user = test_user_with_tokens["user"]
    agent = await _make_agent(db_session, user.id)
    service = AgentRunService(db_session)

    r1 = await service.enqueue(agent.id)
    await asyncio.sleep(0.02)
    r2 = await service.enqueue(agent.id)
    await asyncio.sleep(0.02)
    r3 = await service.enqueue(agent.id)
    await service.claim(r2.id)  # take r2 out of queue

    queued = await service.list_queued(limit=10)
    ids = [q.id for q in queued]
    assert ids == [r1.id, r3.id]
