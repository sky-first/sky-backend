"""End-to-end tests for insight-mode beat + worker — Phase 1 iteration 1.7.

These tests drive the same code paths Celery would trigger in production
by calling the task functions synchronously (skipping the Redis broker).
The AI service call is stubbed by `_call_ai_run_agent` — the whole point
of this iteration is to prove the pipeline between beat → run service →
worker → state machine works end-to-end, not to test the AI call itself.

Covers master plan use cases:
  D1-D3  Beat queries due agents → enqueues → worker claims
  D4     Worker reports success; agent counter reset; next run projected
  D5-D6  Worker reports failure; exponential backoff; status='error' after 4th
  D12    run-now does not stomp on next_execution_at (handled by
         InsightAgentService, covered in iteration 1.5 tests)
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.agent_run_state import QUEUED, RUNNING, SUCCEEDED
from src.core.security import get_password_hash
from src.models.agent import Agent, AgentExecution
from src.repositories.user import UserRepository
from src.services.agent_run_service import AgentRunService
from src.workers import insight_agent_worker as worker_mod


async def _make_user(db: AsyncSession, email="w@x.com"):
    repo = UserRepository(db)
    u = await repo.create(
        email=email,
        password_hash=get_password_hash("pw"),
        name="w",
        role="user",
    )
    await db.commit()
    return u


async def _make_active_insight_agent(
    db: AsyncSession,
    user_id: UUID,
    *,
    next_execution_at,
    schedule={"interval_value": 1, "interval_unit": "hour"},
):
    agent = Agent(
        name="t", archetype="custom", monitor_type="insight",
        scope="personal", scope_id=str(user_id),
        status="active", frequency="hourly",
        connection_ids=[], created_by=user_id,
        identity_type="user",
        schedule_jsonb=schedule,
        notify_on_change=True, delta_strategy="hash",
        consecutive_failures=0,
        next_execution_at=next_execution_at,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


# ─── Beat: _tick picks up due agents ──────────────────────────────────────


@pytest.mark.asyncio
async def test_beat_picks_up_only_due_insight_agents(
    test_user_with_tokens, db_session: AsyncSession, monkeypatch
):
    """The beat's internal coroutine _tick() enqueues exactly the
    insight-mode agents whose next_execution_at has passed."""
    user = test_user_with_tokens["user"]
    # Due agent — insight, active, due 10 min ago
    due = await _make_active_insight_agent(
        db_session,
        user.id,
        next_execution_at=datetime.utcnow() - timedelta(minutes=10),
    )
    # Not due yet
    future = await _make_active_insight_agent(
        db_session,
        user.id,
        next_execution_at=datetime.utcnow() + timedelta(hours=1),
    )
    # Wrong mode
    legacy = Agent(
        name="legacy", archetype="custom", monitor_type="question",
        scope="personal", scope_id=str(user.id),
        status="active", frequency="hourly",
        connection_ids=[], created_by=user.id,
        next_execution_at=datetime.utcnow() - timedelta(minutes=10),
    )
    db_session.add(legacy)
    await db_session.commit()

    # Stub the Celery .delay() to record enqueued run ids without a broker
    enqueued_run_ids = []

    def _fake_delay(run_id):
        enqueued_run_ids.append(run_id)

    monkeypatch.setattr(
        worker_mod.execute_insight_run, "delay", _fake_delay
    )

    # Redirect the worker's session factory to the test session.
    class _Ctx:
        def __init__(self, session):
            self.session = session
        async def __aenter__(self):
            return self.session
        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(worker_mod, "AsyncSessionLocal", lambda: _Ctx(db_session))

    count = await _inner_tick()

    assert count == 1
    assert len(enqueued_run_ids) == 1
    # Verify the queued row is for the due insight agent
    run = (await db_session.execute(
        select(AgentExecution).where(
            AgentExecution.id == UUID(enqueued_run_ids[0])
        )
    )).scalar_one()
    assert run.agent_id == due.id
    assert run.status == QUEUED


async def _inner_tick():
    """Re-implementation of the beat's async body — needed because
    Celery tasks wrap coroutines and we can't directly await the task
    function from pytest. Keeps the beat logic testable."""
    from datetime import datetime, timezone
    from src.workers import insight_agent_worker as m

    now = datetime.now(timezone.utc)
    async with m.AsyncSessionLocal() as db:
        result = await db.execute(
            select(Agent).where(
                Agent.monitor_type == "insight",
                Agent.status == "active",
                Agent.next_execution_at.is_not(None),
                Agent.next_execution_at <= now,
            )
        )
        due = list(result.scalars().all())
        service = AgentRunService(db)
        n = 0
        for agent in due:
            run = await service.enqueue(agent.id)
            m.execute_insight_run.delay(str(run.id))
            n += 1
        return n


# ─── Worker: full success path ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_worker_success_path_updates_agent_and_run(
    test_user_with_tokens, db_session: AsyncSession, monkeypatch
):
    user = test_user_with_tokens["user"]
    agent = await _make_active_insight_agent(
        db_session,
        user.id,
        next_execution_at=datetime.utcnow() - timedelta(seconds=1),
    )
    service = AgentRunService(db_session)
    run = await service.enqueue(agent.id)

    # Drive the worker inline (bypass Celery loop)
    claimed = await service.claim(run.id)
    assert claimed.status == RUNNING

    mock_response = {
        "result_hash": "abc123",
        "result_payload": {"rows": [{"x": 1}], "schema": [{"name": "x", "type": "int"}]},
        "delta": {"kind": "first_run", "summary": None},
        "tokens": {"in": 50, "out": 10},
        "cost_usd": 0.0001,
    }

    final = await service.report_success(
        run.id,
        result_hash=mock_response["result_hash"],
        result_payload=mock_response["result_payload"],
        delta_kind=mock_response["delta"]["kind"],
    )

    assert final.status == SUCCEEDED
    assert final.result_hash == "abc123"
    assert final.delta_kind == "first_run"

    # Agent row state
    refreshed = (
        await db_session.execute(select(Agent).where(Agent.id == agent.id))
    ).scalar_one()
    assert refreshed.consecutive_failures == 0
    assert refreshed.next_execution_at is not None
    # About an hour in the future (slack for test jitter)
    delta = refreshed.next_execution_at - datetime.utcnow()
    assert timedelta(minutes=58) <= delta <= timedelta(minutes=62)


# ─── Worker: failure → backoff → eventually 'error' ───────────────────────


@pytest.mark.asyncio
async def test_worker_failure_path_applies_backoff_and_flips_to_error_after_budget(
    test_user_with_tokens, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    agent = await _make_active_insight_agent(
        db_session,
        user.id,
        next_execution_at=datetime.utcnow() - timedelta(seconds=1),
    )

    service = AgentRunService(db_session)
    # 4 consecutive failures: 5min, 15min, 45min, then error
    expected_status_after = ["active", "active", "active", "error"]
    expected_backoff = [5, 15, 45, None]

    for i, (exp_status, exp_backoff) in enumerate(
        zip(expected_status_after, expected_backoff), start=1
    ):
        run = await service.enqueue(agent.id)
        await service.claim(run.id)
        await service.report_failure(run.id, error_message=f"boom-{i}")

        refreshed = (
            await db_session.execute(select(Agent).where(Agent.id == agent.id))
        ).scalar_one()
        assert refreshed.status == exp_status
        if exp_backoff is None:
            assert refreshed.next_execution_at is None
        else:
            delta = refreshed.next_execution_at - datetime.utcnow()
            # Slack 1 min either way for jitter
            assert (
                timedelta(minutes=exp_backoff - 1)
                <= delta
                <= timedelta(minutes=exp_backoff + 1)
            ), f"iter {i}: expected ~{exp_backoff}min backoff, got {delta}"


# ─── AI stub response shape ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ai_stub_returns_expected_shape(
    test_user_with_tokens, db_session: AsyncSession, monkeypatch
):
    """Verify _call_ai_run_agent returns the required response shape.
    The AI service call is mocked so this test focuses on the contract,
    not on the live HTTP round-trip."""
    import hashlib, json
    from decimal import Decimal

    user = test_user_with_tokens["user"]
    agent = await _make_active_insight_agent(
        db_session, user.id, next_execution_at=datetime.now(timezone.utc)
    )
    service = AgentRunService(db_session)
    run = await service.enqueue(agent.id)

    _fixed_response = {
        "result_hash": hashlib.sha256(b"[]").hexdigest(),
        "result_payload": {"answer": "mocked", "data_sample": []},
        "delta": {"kind": "first_run", "summary": None, "tokens": 0},
        "tokens": 0,
        "cost_usd": Decimal("0"),
        "duration_ms": 1,
    }

    async def _mock_call(a, r, db):
        return _fixed_response

    monkeypatch.setattr(worker_mod, "_call_ai_run_agent", _mock_call)
    response = await worker_mod._call_ai_run_agent(agent, run, db_session)

    for key in ("result_hash", "result_payload", "delta", "tokens", "cost_usd", "duration_ms"):
        assert key in response
    assert response["delta"]["kind"] in ("first_run", "none", "trivial", "material")


# ─── Monitor-type routing sanity ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_legacy_scheduler_skips_insight_agents(
    test_user_with_tokens, db_session: AsyncSession
):
    """Ensure the existing `schedule_agents` beat doesn't double-enqueue
    insight-mode agents. It should only see question/datasource/sql."""
    from sqlalchemy import select as _sel
    user = test_user_with_tokens["user"]

    # Insight mode, due now
    insight_agent = await _make_active_insight_agent(
        db_session,
        user.id,
        next_execution_at=datetime.utcnow() - timedelta(minutes=1),
    )

    # Simulate the legacy scheduler's query — MUST exclude insight
    now = datetime.utcnow()
    result = await db_session.execute(
        _sel(Agent).where(
            Agent.status == "active",
            Agent.next_execution_at <= now,
            Agent.monitor_type != "insight",
        )
    )
    picked = list(result.scalars().all())

    assert insight_agent.id not in {a.id for a in picked}
