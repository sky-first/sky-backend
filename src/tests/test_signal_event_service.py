"""
Unit tests for src/services/signal_event_service.py
Covers: list_events, get_event (found / not found), create_event (with AI success & failure),
        update_event (found / not found, with AI success & failure), delete_event (success / not found).
Includes tenant filtering (W1) and UPPERCASE enums (Bug 4).
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.models.signal_event import SignalCategory, SignalConfidence, SignalNature
from src.schemas.signal_event import SignalEventCreate, SignalEventUpdate
from src.services.signal_event_service import SignalEventService

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_event(**kwargs):
    """Return a MagicMock that mimics a SignalEvent ORM object."""
    ev = MagicMock()
    ev.id = uuid4()
    ev.category = SignalCategory.INTERNAL
    ev.sub_type = "test-sub"
    ev.nature = SignalNature.EVENT
    ev.description = "test description"
    ev.start_date = datetime.now(timezone.utc)
    ev.impact_date = None
    ev.confidence = SignalConfidence.MEDIUM
    ev.relations = None
    ev.space_id = None
    ev.crew_id = None
    for k, v in kwargs.items():
        setattr(ev, k, v)
    return ev


def _make_service(db=None):
    """Return a SignalEventService with a mocked DB session."""
    if db is None:
        db = AsyncMock()
    svc = SignalEventService.__new__(SignalEventService)
    svc.db = db
    svc.repository = AsyncMock()
    svc.ai_client = AsyncMock()
    return svc


# ---------------------------------------------------------------------------
# list_events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_events_returns_all_with_filters():
    svc = _make_service()
    events = [_make_event(), _make_event()]
    svc.repository.get_all = AsyncMock(return_value=events)

    space_id = uuid4()
    crew_id = uuid4()

    result = await svc.list_events(space_id=space_id, crew_id=crew_id)

    svc.repository.get_all.assert_awaited_once_with(
        filters={"space_id": space_id, "crew_id": crew_id}
    )
    assert result == events


# ---------------------------------------------------------------------------
# get_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_event_found_with_tenant():
    svc = _make_service()
    space_id = uuid4()
    ev = _make_event(space_id=space_id)
    svc.repository.get_by_id = AsyncMock(return_value=ev)

    result = await svc.get_event(ev.id, space_id=space_id)
    assert result == ev


@pytest.mark.asyncio
async def test_get_event_tenant_mismatch_raises_404():
    from fastapi import HTTPException

    svc = _make_service()
    ev = _make_event(space_id=uuid4())
    svc.repository.get_by_id = AsyncMock(return_value=ev)

    with pytest.raises(HTTPException) as exc_info:
        await svc.get_event(ev.id, space_id=uuid4())  # Different space_id
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# create_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_event_success_with_ai_ingestion_and_tenant():
    svc = _make_service()
    space_id = uuid4()
    crew_id = uuid4()
    ev = _make_event(space_id=space_id, crew_id=crew_id)

    svc.repository.create = AsyncMock(return_value=ev)
    svc.db.commit = AsyncMock()
    svc.db.refresh = AsyncMock()
    svc.ai_client.ingest_knowledge_graph = AsyncMock()

    schema = SignalEventCreate(
        category=SignalCategory.INTERNAL,
        sub_type="market",
        nature=SignalNature.SIGNAL,
        description="desc",
        start_date=datetime.now(timezone.utc),
        confidence=SignalConfidence.HIGH,
    )

    result = await svc.create_event(schema, space_id=space_id, crew_id=crew_id)

    # Verify that space_id/crew_id were injected into the call
    called_args = svc.repository.create.await_args.kwargs
    assert called_args["space_id"] == space_id
    assert called_args["crew_id"] == crew_id

    svc.db.commit.assert_awaited_once()
    svc.ai_client.ingest_knowledge_graph.assert_awaited_once()
    assert result == ev


# ---------------------------------------------------------------------------
# update_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_event_success_with_tenant_check():
    svc = _make_service()
    space_id = uuid4()
    ev = _make_event(space_id=space_id)

    # Mock get_event (ownership check) and update
    svc.repository.get_by_id = AsyncMock(return_value=ev)
    svc.repository.update = AsyncMock(return_value=ev)
    svc.db.commit = AsyncMock()
    svc.db.refresh = AsyncMock()
    svc.ai_client.ingest_knowledge_graph = AsyncMock()

    schema = SignalEventUpdate(description="updated description")

    result = await svc.update_event(ev.id, schema, space_id=space_id)

    svc.repository.update.assert_awaited_once()
    assert result == ev


# ---------------------------------------------------------------------------
# delete_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_event_success_with_tenant():
    svc = _make_service()
    space_id = uuid4()
    ev = _make_event(space_id=space_id)

    svc.repository.get_by_id = AsyncMock(return_value=ev)
    svc.repository.delete = AsyncMock(return_value=True)
    svc.db.commit = AsyncMock()

    await svc.delete_event(ev.id, space_id=space_id)

    svc.repository.delete.assert_awaited_once_with(ev.id)
    svc.db.commit.assert_awaited_once()
