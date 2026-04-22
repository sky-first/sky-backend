"""Round-trip tests for agents.chat_context.

The field is written by the frontend's "Create agent from this chat"
CTA — the chat transcript travels with the agent so subsequent runs
can reference the conversation that motivated the agent. These tests
pin:
  1. AgentCreate accepts chat_context (optional string).
  2. AgentService.create_agent persists it on the row.
  3. AgentUpdate accepts chat_context and the service updates it.
  4. AgentResponse / AgentListResponse expose it on reads.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.models.agent import Agent
from src.schemas.agent import (
    AgentCreate,
    AgentListResponse,
    AgentResponse,
    AgentUpdate,
)
from src.services.agent_service import AgentService


# ─── schema-level ─────────────────────────────────────────────────────────

def test_agent_create_accepts_chat_context():
    transcript = "User: what's our churn?\n\nAssistant: 3.4% this month..."
    a = AgentCreate(
        name="Churn watch",
        scope_id=str(uuid4()),
        chat_context=transcript,
    )
    assert a.chat_context == transcript


def test_agent_create_chat_context_defaults_to_none():
    a = AgentCreate(name="X", scope_id=str(uuid4()))
    assert a.chat_context is None


def test_agent_update_accepts_chat_context():
    u = AgentUpdate(chat_context="Updated transcript")
    assert u.chat_context == "Updated transcript"


def test_agent_update_chat_context_is_optional():
    # model_dump(exclude_unset=True) must omit the field when the caller
    # didn't touch it — otherwise update_agent would wipe chat_context
    # every time the user edited, say, the frequency.
    u = AgentUpdate(frequency=None)
    dumped = u.model_dump(exclude_unset=True)
    assert "chat_context" not in dumped


def test_agent_response_exposes_chat_context():
    # Build a fake ORM-shape dict and feed AgentResponse.model_validate —
    # mirrors how FastAPI serializes SQLAlchemy rows.
    payload = _fake_agent_payload(chat_context="from chat")
    r = AgentResponse.model_validate(payload)
    assert r.chat_context == "from chat"


def test_agent_list_response_exposes_chat_context():
    payload = _fake_agent_payload(chat_context="carry me")
    r = AgentListResponse.model_validate(payload)
    assert r.chat_context == "carry me"


# ─── service-level round-trip ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_service_create_agent_persists_chat_context(db_session):
    transcript = "User: hey\n\nAssistant: hi!"
    service = AgentService(db_session)
    created = await service.create_agent(
        AgentCreate(
            name="With-chat",
            scope_id=str(uuid4()),
            chat_context=transcript,
            connection_ids=[],
        ),
        user_id=uuid4(),
    )
    assert created.chat_context == transcript


@pytest.mark.asyncio
async def test_service_update_agent_preserves_chat_context_when_not_set(db_session):
    # Updating a field that isn't chat_context must not blank out an
    # existing chat_context value.
    transcript = "the original transcript"
    service = AgentService(db_session)
    created = await service.create_agent(
        AgentCreate(
            name="Preserve",
            scope_id=str(uuid4()),
            chat_context=transcript,
            connection_ids=[],
        ),
        user_id=uuid4(),
    )
    updated = await service.update_agent(
        created.id,
        AgentUpdate(name="Preserve (renamed)"),
    )
    assert updated.chat_context == transcript
    assert updated.name == "Preserve (renamed)"


# ─── helpers ──────────────────────────────────────────────────────────────

def _fake_agent_payload(*, chat_context: str | None) -> dict:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return {
        "id": uuid4(),
        "name": "t",
        "archetype": "custom",
        "scope": "space",
        "scope_id": str(uuid4()),
        "scope_name": None,
        "status": "active",
        "monitor_type": "question",
        "focus": None,
        "custom_sql": None,
        "chat_context": chat_context,
        "frequency": "daily",
        "depth": "standard",
        "connection_ids": [],
        "table_ids": None,
        "space_ids": None,
        "relationship_types": None,
        "last_execution_at": None,
        "next_execution_at": None,
        "executions_this_month": 0,
        "cycles_consumed": 0,
        "created_at": now,
        "updated_at": now,
    }


__all__ = ["Agent", "UUID"]  # silence "imported but unused" on ORM-only import
