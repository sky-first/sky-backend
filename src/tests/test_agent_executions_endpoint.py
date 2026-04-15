"""Tests for the Agent Activity feed endpoint — Phase 3.5.

Covers the cross-agent executions list served to Settings → Agent
Activity. Security is as important as correctness here: the endpoint
MUST NOT leak executions from another user's agents even when the
caller passes their agent_id.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token
from src.models.agent import (
    Agent,
    AgentExecution,
    AgentFrequency,
    AgentScope,
)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_agent(db: AsyncSession, *, user_id, name: str) -> Agent:
    agent = Agent(
        name=name,
        scope=AgentScope.PERSONAL,
        scope_id=str(uuid.uuid4()),
        scope_name="self",
        frequency=AgentFrequency.DAILY,
        focus="?",
        created_by=user_id,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _make_execution(
    db: AsyncSession,
    *,
    agent_id,
    status_str: str = "succeeded",
    context_doc_ids: list[str] | None = None,
    context_intent: str | None = None,
    delta_kind: str | None = "first_run",
) -> AgentExecution:
    e = AgentExecution(
        agent_id=agent_id,
        status=status_str,
        context_doc_ids=context_doc_ids or [],
        context_intent=context_intent,
        delta_kind=delta_kind,
        started_at=datetime.now(timezone.utc),
    )
    db.add(e)
    await db.flush()
    return e


# ─── X1 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_lists_only_the_callers_executions(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession
):
    """User A sees executions for their own agents, not for user B's."""
    user_a = test_user_with_tokens["user"]
    agent_a = await _make_agent(db_session, user_id=user_a.id, name="Mine")
    await _make_execution(db_session, agent_id=agent_a.id)

    # Plant another user's agent + execution that must NOT appear.
    from src.core.security import get_password_hash
    from src.models.user import User

    other = User(
        email="other@example.com",
        password_hash=get_password_hash("x"),
        name="Other",
        role="user",
    )
    db_session.add(other)
    await db_session.flush()
    agent_b = await _make_agent(db_session, user_id=other.id, name="Theirs")
    await _make_execution(db_session, agent_id=agent_b.id)

    await db_session.commit()

    resp = await async_client.get(
        "/api/v1/agents/insight/executions",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert {row["agent_name"] for row in data} == {"Mine"}


# ─── X2 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_returns_evidence_trail(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    agent = await _make_agent(db_session, user_id=user.id, name="Revenue")
    doc_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    await _make_execution(
        db_session,
        agent_id=agent.id,
        context_doc_ids=doc_ids,
        context_intent="strategy",
    )
    await db_session.commit()

    resp = await async_client.get(
        "/api/v1/agents/insight/executions",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["context_intent"] == "strategy"
    assert len(data[0]["context_doc_ids"]) == 2


# ─── X3 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_filter_by_foreign_agent_id_returns_empty(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession
):
    """Passing ?agent_id= for an agent you don't own yields [] — not 403
    (we don't want to leak whether the agent exists)."""
    from src.core.security import get_password_hash
    from src.models.user import User

    other = User(
        email="other2@example.com",
        password_hash=get_password_hash("x"),
        name="Other",
        role="user",
    )
    db_session.add(other)
    await db_session.flush()
    agent_b = await _make_agent(db_session, user_id=other.id, name="NotMine")
    await _make_execution(db_session, agent_id=agent_b.id)

    # Caller has at least one of their own so the empty-owned short-
    # circuit doesn't fire.
    me_agent = await _make_agent(
        db_session, user_id=test_user_with_tokens["user"].id, name="Me"
    )
    await _make_execution(db_session, agent_id=me_agent.id)
    await db_session.commit()

    resp = await async_client.get(
        f"/api/v1/agents/insight/executions?agent_id={agent_b.id}",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json() == []


# ─── X4 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_respects_limit(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    agent = await _make_agent(db_session, user_id=user.id, name="Many")
    for _ in range(7):
        await _make_execution(db_session, agent_id=agent.id)
    await db_session.commit()

    resp = await async_client.get(
        "/api/v1/agents/insight/executions?limit=3",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 3


# ─── X5 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_no_agents_returns_empty_quickly(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession
):
    resp = await async_client.get(
        "/api/v1/agents/insight/executions",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json() == []
