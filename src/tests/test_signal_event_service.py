"""
Unit tests for src/services/signal_event_service.py
Covers: list_events, get_event (found / not found), create_event (with AI success & failure),
        update_event (found / not found, with AI success & failure), delete_event (success / not found).
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
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
async def test_list_events_returns_all():
    svc = _make_service()
    events = [_make_event(), _make_event()]
    svc.repository.get_all = AsyncMock(return_value=events)

    result = await svc.list_events()

    svc.repository.get_all.assert_awaited_once()
    assert result == events


# ---------------------------------------------------------------------------
# get_event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_event_found():
    svc = _make_service()
    ev = _make_event()
    svc.repository.get_by_id = AsyncMock(return_value=ev)

    result = await svc.get_event(ev.id)
    assert result == ev


@pytest.mark.asyncio
async def test_get_event_not_found_raises_404():
    from fastapi import HTTPException

    svc = _make_service()
    svc.repository.get_by_id = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await svc.get_event(uuid4())
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# create_event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_event_success_with_ai_ingestion():
    svc = _make_service()
    ev = _make_event()

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

    result = await svc.create_event(schema)

    svc.repository.create.assert_awaited_once()
    svc.db.commit.assert_awaited_once()
    svc.db.refresh.assert_awaited_once_with(ev)
    svc.ai_client.ingest_knowledge_graph.assert_awaited_once()
    assert result == ev


@pytest.mark.asyncio
async def test_create_event_ai_failure_does_not_raise():
    """AI ingestion failure should be caught and logged, not propagate."""
    svc = _make_service()
    ev = _make_event()

    svc.repository.create = AsyncMock(return_value=ev)
    svc.db.commit = AsyncMock()
    svc.db.refresh = AsyncMock()
    svc.ai_client.ingest_knowledge_graph = AsyncMock(side_effect=Exception("AI down"))

    schema = SignalEventCreate(
        category=SignalCategory.EXTERNAL,
        sub_type="trend",
        nature=SignalNature.HYPOTHESIS,
        description="some hypothesis",
        start_date=datetime.now(timezone.utc),
        confidence=SignalConfidence.LOW,
    )

    # Should NOT raise even though AI failed
    result = await svc.create_event(schema)
    assert result == ev


@pytest.mark.asyncio
async def test_create_event_with_impact_date_and_relations():
    """Covers branches for optional fields: impact_date, space_id, crew_id, relations."""
    svc = _make_service()
    space_id = uuid4()
    crew_id = uuid4()
    impact = datetime.now(timezone.utc)
    ev = _make_event(
        impact_date=impact,
        space_id=space_id,
        crew_id=crew_id,
        relations={"kpi": "revenue"},
    )

    svc.repository.create = AsyncMock(return_value=ev)
    svc.db.commit = AsyncMock()
    svc.db.refresh = AsyncMock()
    svc.ai_client.ingest_knowledge_graph = AsyncMock()

    schema = SignalEventCreate(
        category=SignalCategory.TRENDS,
        sub_type="macro",
        nature=SignalNature.EVENT,
        description="trend desc",
        start_date=datetime.now(timezone.utc),
        impact_date=impact,
        confidence=SignalConfidence.MEDIUM,
        relations={"kpi": "revenue"},
        space_id=space_id,
        crew_id=crew_id,
    )

    result = await svc.create_event(schema)
    assert result == ev


# ---------------------------------------------------------------------------
# update_event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_event_success_with_ai_ingestion():
    svc = _make_service()
    ev = _make_event()

    svc.repository.update = AsyncMock(return_value=ev)
    svc.db.commit = AsyncMock()
    svc.db.refresh = AsyncMock()
    svc.ai_client.ingest_knowledge_graph = AsyncMock()

    schema = SignalEventUpdate(description="updated description")

    result = await svc.update_event(ev.id, schema)

    svc.repository.update.assert_awaited_once()
    svc.db.commit.assert_awaited_once()
    svc.db.refresh.assert_awaited_once_with(ev)
    svc.ai_client.ingest_knowledge_graph.assert_awaited_once()
    assert result == ev


@pytest.mark.asyncio
async def test_update_event_not_found_raises_404():
    from fastapi import HTTPException

    svc = _make_service()
    svc.repository.update = AsyncMock(return_value=None)

    schema = SignalEventUpdate(description="x")

    with pytest.raises(HTTPException) as exc_info:
        await svc.update_event(uuid4(), schema)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_update_event_ai_failure_does_not_raise():
    svc = _make_service()
    ev = _make_event(impact_date=datetime.now(timezone.utc), space_id=uuid4(), crew_id=uuid4())

    svc.repository.update = AsyncMock(return_value=ev)
    svc.db.commit = AsyncMock()
    svc.db.refresh = AsyncMock()
    svc.ai_client.ingest_knowledge_graph = AsyncMock(side_effect=RuntimeError("timeout"))

    schema = SignalEventUpdate(confidence=SignalConfidence.HIGH)

    # Should NOT raise
    result = await svc.update_event(ev.id, schema)
    assert result == ev


# ---------------------------------------------------------------------------
# delete_event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_event_success():
    svc = _make_service()
    svc.repository.delete = AsyncMock(return_value=True)
    svc.db.commit = AsyncMock()

    await svc.delete_event(uuid4())  # should not raise

    svc.db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_event_not_found_raises_404():
    from fastapi import HTTPException

    svc = _make_service()
    svc.repository.delete = AsyncMock(return_value=False)

    with pytest.raises(HTTPException) as exc_info:
        await svc.delete_event(uuid4())
    assert exc_info.value.status_code == 404
