"""Tests for AgentService.create_agent in personal mode (Lucas QA 2026-05-30).

Lucas reported that creating an agent in modo PERSONAL was blocked. The
FE wizard does not always carry a valid scope_id when the user has not
picked a Space, and the old code refused to create the row.

The service layer now normalises personal agents so scope_id == created_by
regardless of what the client posted, and the route accepts the request
without a scope_id for personal scope.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.agent import AgentArchetype, AgentFrequency, AgentScope
from src.schemas.agent import AgentCreate
from src.services.agent_service import AgentService


@pytest.mark.asyncio
async def test_create_personal_agent_normalises_scope_id_to_user_id(
    test_user_with_tokens: dict, db_session: AsyncSession
):
    """create_agent must stamp scope_id = user.id when scope=personal,
    even if the caller posted a different (or empty) string."""
    user = test_user_with_tokens["user"]
    svc = AgentService(db_session)

    payload = AgentCreate(
        name="Personal scout",
        archetype=AgentArchetype.CUSTOM,
        scope=AgentScope.PERSONAL,
        # Empty — mimics the modo PERSONAL wizard posting before a Space pick.
        scope_id=None,
        monitor_type="question",
        focus="Watch personal data",
        frequency=AgentFrequency.DAILY,
        connection_ids=[],
    )

    agent = await svc.create_agent(payload, user_id=user.id)

    assert agent is not None
    assert agent.scope == "personal"
    # The service must overwrite scope_id with user.id so personal-owner
    # checks (e.g. _require_can_mutate) consistently identify the owner.
    assert agent.scope_id == str(user.id)
    assert agent.created_by == user.id


@pytest.mark.asyncio
async def test_create_personal_agent_overrides_foreign_scope_id(
    test_user_with_tokens: dict, db_session: AsyncSession
):
    """Even when the FE posts a stale / foreign scope_id for a personal
    agent, the service should hard-pin scope_id to the creator. This is
    a defence-in-depth: matching scope_id ≠ user.id would otherwise lock
    the creator out of their own agent via _require_can_mutate."""
    import uuid as _uuid

    user = test_user_with_tokens["user"]
    svc = AgentService(db_session)

    payload = AgentCreate(
        name="Foreign-scope personal",
        archetype=AgentArchetype.CUSTOM,
        scope=AgentScope.PERSONAL,
        scope_id=str(_uuid.uuid4()),  # bogus — service must ignore
        monitor_type="question",
        focus="Watch personal data",
        frequency=AgentFrequency.DAILY,
        connection_ids=[],
    )

    agent = await svc.create_agent(payload, user_id=user.id)

    assert agent.scope_id == str(user.id)
