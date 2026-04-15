"""Tests for admin pause-all + audit export — Phase 5.5."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.agent import (
    Agent,
    AgentExecution,
    AgentFrequency,
    AgentScope,
    AgentStatus,
)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _agent(db: AsyncSession, *, user_id, status_val: str = "active") -> Agent:
    a = Agent(
        name="X",
        scope=AgentScope.PERSONAL,
        scope_id=str(uuid.uuid4()),
        scope_name="self",
        frequency=AgentFrequency.DAILY,
        focus="?",
        created_by=user_id,
        status=status_val,
        next_execution_at=datetime.now(timezone.utc),
    )
    db.add(a)
    await db.flush()
    return a


# ─── pause-all ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_pause_all_forbidden_for_non_admin(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession
):
    test_user_with_tokens["user"].role = "user"
    await db_session.commit()
    resp = await async_client.post(
        "/api/v1/admin/agents/pause-all",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_pause_all_pauses_active_agents_and_clears_next_run(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession
):
    test_user_with_tokens["user"].role = "admin"
    # 3 active + 1 already paused (must not be touched).
    a1 = await _agent(db_session, user_id=test_user_with_tokens["user"].id, status_val="active")
    a2 = await _agent(db_session, user_id=test_user_with_tokens["user"].id, status_val="active")
    a3 = await _agent(db_session, user_id=test_user_with_tokens["user"].id, status_val="active")
    already = await _agent(db_session, user_id=test_user_with_tokens["user"].id, status_val="paused")
    await db_session.commit()

    resp = await async_client.post(
        "/api/v1/admin/agents/pause-all",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["paused_count"] == 3
    assert set(body["agent_ids"]) == {str(a1.id), str(a2.id), str(a3.id)}

    # Each paused agent has status='paused' and next_execution_at=None.
    await db_session.refresh(a1)
    await db_session.refresh(a2)
    await db_session.refresh(a3)
    await db_session.refresh(already)
    for a in (a1, a2, a3):
        # Accept either AgentStatus.PAUSED enum or raw string "paused"
        # — the model round-trip preserves whatever the column holds.
        assert str(a.status).lower().endswith("paused")
        assert a.next_execution_at is None

    # Already-paused agent keeps its pre-existing next_execution_at
    # value — we don't touch rows that were already off.
    assert already.next_execution_at is not None


@pytest.mark.asyncio
async def test_pause_all_is_idempotent(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession
):
    """Second call returns 0 paused (nothing active to pause)."""
    test_user_with_tokens["user"].role = "admin"
    await _agent(db_session, user_id=test_user_with_tokens["user"].id, status_val="active")
    await db_session.commit()

    first = await async_client.post(
        "/api/v1/admin/agents/pause-all",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert first.json()["paused_count"] == 1

    second = await async_client.post(
        "/api/v1/admin/agents/pause-all",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert second.status_code == 200
    assert second.json()["paused_count"] == 0


@pytest.mark.asyncio
async def test_pause_all_scoped_by_space(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession
):
    """Passing ?space_id= limits the pause to that scope."""
    test_user_with_tokens["user"].role = "admin"
    space_a = str(uuid.uuid4())
    space_b = str(uuid.uuid4())
    in_a = Agent(
        name="a", scope=AgentScope.SPACE, scope_id=space_a, scope_name="A",
        frequency=AgentFrequency.DAILY, focus="?", created_by=test_user_with_tokens["user"].id,
        status="active",
    )
    in_b = Agent(
        name="b", scope=AgentScope.SPACE, scope_id=space_b, scope_name="B",
        frequency=AgentFrequency.DAILY, focus="?", created_by=test_user_with_tokens["user"].id,
        status="active",
    )
    db_session.add_all([in_a, in_b])
    await db_session.commit()

    resp = await async_client.post(
        f"/api/v1/admin/agents/pause-all?space_id={space_a}",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["paused_count"] == 1

    # Agent in space B is untouched.
    await db_session.refresh(in_b)
    assert str(in_b.status).lower().endswith("active")


# ─── audit export ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_audit_export_forbidden_for_non_admin(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession
):
    test_user_with_tokens["user"].role = "user"
    await db_session.commit()
    resp = await async_client.get(
        "/api/v1/admin/audit/executions.csv",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_audit_export_streams_csv_with_evidence_trail(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession
):
    test_user_with_tokens["user"].role = "admin"
    agent = await _agent(db_session, user_id=test_user_with_tokens["user"].id)
    doc_id = str(uuid.uuid4())
    exec_ = AgentExecution(
        agent_id=agent.id,
        status="succeeded",
        delta_kind="material",
        delta_summary="Revenue dropped 8%",
        context_intent="strategy",
        context_doc_ids=[doc_id],
        llm_tokens_used=500,
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(exec_)
    await db_session.commit()

    resp = await async_client.get(
        "/api/v1/admin/audit/executions.csv",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    body = resp.text
    # Header row
    assert "execution_id,agent_id,agent_name,status" in body
    # Our seeded row — evidence trail preserved
    assert "material" in body
    assert "strategy" in body
    assert doc_id in body
    assert "500" in body
