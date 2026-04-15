"""Tests for the context-evidence trail on agent_executions — Phase 2.6.

The AI service will populate `context_doc_ids` and `context_intent` when
an agent run invokes the brain. These tests only verify that the columns
round-trip through the ORM / SQLite test bed — the production writes
happen from the AI service via raw SQL in Phase 2.6b.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.agent import Agent, AgentExecution, AgentFrequency, AgentScope


@pytest.mark.asyncio
async def test_execution_defaults_to_empty_evidence(db_session: AsyncSession):
    agent = Agent(
        name="X",
        scope=AgentScope.PERSONAL,
        scope_id=str(uuid.uuid4()),
        scope_name="self",
        frequency=AgentFrequency.DAILY,
        focus="q?",
    )
    db_session.add(agent)
    await db_session.flush()

    exec_ = AgentExecution(agent_id=agent.id, status="completed")
    db_session.add(exec_)
    await db_session.commit()
    await db_session.refresh(exec_)

    assert list(exec_.context_doc_ids or []) == []
    assert exec_.context_intent is None


@pytest.mark.asyncio
async def test_execution_persists_evidence_ids(db_session: AsyncSession):
    agent = Agent(
        name="X",
        scope=AgentScope.PERSONAL,
        scope_id=str(uuid.uuid4()),
        scope_name="self",
        frequency=AgentFrequency.DAILY,
        focus="q?",
    )
    db_session.add(agent)
    await db_session.flush()

    # SQLite's JSON fallback can't serialize UUID objects — production
    # Postgres uses native ARRAY(UUID) so this is test-bed-only.
    doc_ids = [str(uuid.uuid4()) for _ in range(3)]
    exec_ = AgentExecution(
        agent_id=agent.id,
        status="completed",
        context_doc_ids=doc_ids,
        context_intent="strategy",
    )
    db_session.add(exec_)
    await db_session.commit()
    await db_session.refresh(exec_)

    assert len(exec_.context_doc_ids) == 3
    assert exec_.context_intent == "strategy"
