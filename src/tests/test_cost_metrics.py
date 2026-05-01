"""Tests for /settings/metrics/cost — Phase 5.2/5.3."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.agent import (
    Agent,
    AgentExecution,
    AgentFrequency,
    AgentScope,
)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _agent(db: AsyncSession, *, user_id, scope: AgentScope, scope_id: str) -> Agent:
    a = Agent(
        name=f"a-{scope_id[:6]}",
        scope=scope,
        scope_id=scope_id,
        scope_name="x",
        frequency=AgentFrequency.DAILY,
        focus="?",
        created_by=user_id,
    )
    db.add(a)
    await db.flush()
    return a


async def _exec(
    db: AsyncSession, *, agent_id, cost: float, tokens: int, started_at: datetime
):
    db.add(
        AgentExecution(
            agent_id=agent_id,
            status="succeeded",
            llm_cost_usd=Decimal(str(cost)),
            llm_tokens_used=tokens,
            started_at=started_at,
            finished_at=started_at + timedelta(seconds=2),
        )
    )
    await db.flush()


# ─── C1 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_cost_endpoint_returns_empty_when_no_data(
    test_user_with_tokens, async_client: AsyncClient
):
    resp = await async_client.get(
        "/api/v1/settings/metrics/cost",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cost_usd"] == 0.0
    assert data["total_tokens"] == 0
    assert data["by_crew"] == []
    assert data["daily"] == []
    assert data["window_days"] == 30


# ─── C2 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_cost_buckets_by_scope_and_totals_match(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession
):
    uid = test_user_with_tokens["user"].id
    now = datetime.now(timezone.utc)

    a_personal = await _agent(
        db_session, user_id=uid, scope=AgentScope.PERSONAL, scope_id=str(uuid.uuid4())
    )
    a_space = await _agent(
        db_session, user_id=uid, scope=AgentScope.SPACE, scope_id=str(uuid.uuid4())
    )
    await db_session.flush()

    await _exec(db_session, agent_id=a_personal.id, cost=0.25, tokens=100, started_at=now - timedelta(days=1))
    await _exec(db_session, agent_id=a_personal.id, cost=0.75, tokens=200, started_at=now - timedelta(days=2))
    await _exec(db_session, agent_id=a_space.id, cost=1.00, tokens=400, started_at=now - timedelta(days=1))
    await db_session.commit()

    resp = await async_client.get(
        "/api/v1/settings/metrics/cost",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cost_usd"] == pytest.approx(2.0)
    assert data["total_tokens"] == 700
    # Per-bucket totals sum to the grand total.
    bucket_sum = sum(c["total_cost_usd"] for c in data["by_crew"])
    assert bucket_sum == pytest.approx(2.0)
    # Daily series has 2 distinct days.
    assert len(data["daily"]) == 2
    # Daily totals sum to grand total.
    assert sum(d["total_cost_usd"] for d in data["daily"]) == pytest.approx(2.0)


# ─── C3 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_window_days_truncates_older_runs(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession
):
    uid = test_user_with_tokens["user"].id
    now = datetime.now(timezone.utc)
    a = await _agent(
        db_session, user_id=uid, scope=AgentScope.PERSONAL, scope_id=str(uuid.uuid4())
    )
    await db_session.flush()
    # Two runs: one inside window, one outside.
    await _exec(db_session, agent_id=a.id, cost=0.10, tokens=10, started_at=now - timedelta(days=3))
    await _exec(db_session, agent_id=a.id, cost=99.99, tokens=9999, started_at=now - timedelta(days=45))
    await db_session.commit()

    resp = await async_client.get(
        "/api/v1/settings/metrics/cost?window_days=7",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["window_days"] == 7
    assert data["total_cost_usd"] == pytest.approx(0.10)
    assert data["total_tokens"] == 10


# ─── C4 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_window_days_bounds_enforced(
    test_user_with_tokens, async_client: AsyncClient
):
    # 0 and > 180 rejected by FastAPI Query bounds → 422.
    for bad in ("0", "181"):
        r = await async_client.get(
            f"/api/v1/settings/metrics/cost?window_days={bad}",
            headers=_auth(test_user_with_tokens["access_token"]),
        )
        assert r.status_code == 422


# ─── C5 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_daily_series_is_sorted_ascending(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession
):
    uid = test_user_with_tokens["user"].id
    now = datetime.now(timezone.utc)
    a = await _agent(
        db_session, user_id=uid, scope=AgentScope.PERSONAL, scope_id=str(uuid.uuid4())
    )
    await db_session.flush()
    await _exec(db_session, agent_id=a.id, cost=0.01, tokens=1, started_at=now - timedelta(days=5))
    await _exec(db_session, agent_id=a.id, cost=0.01, tokens=1, started_at=now - timedelta(days=1))
    await _exec(db_session, agent_id=a.id, cost=0.01, tokens=1, started_at=now - timedelta(days=3))
    await db_session.commit()

    resp = await async_client.get(
        "/api/v1/settings/metrics/cost",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    days = [d["day"] for d in resp.json()["daily"]]
    assert days == sorted(days)


# ─── C6 — RBAC gate (Phase 7 follow-up) ───────────────────────────────────
@pytest.mark.asyncio
async def test_cost_metrics_denied_for_platform_member(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession
):
    """Tenant-wide cost / spend leaks crew names + budget posture across
    the org. Restricted to platform Owner / Admin — Members get 403.
    Regression for the audit gap surfaced after Phase 7 LIMPEZA GERAL."""
    from src.core.security import create_access_token

    user = test_user_with_tokens["user"]
    user.role = "member"
    db_session.add(user)
    await db_session.commit()

    member_token = create_access_token(
        {"sub": str(user.id), "email": user.email, "role": "member"}
    )

    resp = await async_client.get(
        "/api/v1/settings/metrics/cost",
        headers=_auth(member_token),
    )
    assert resp.status_code == 403, resp.text
