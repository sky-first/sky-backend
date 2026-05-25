"""Glossary — CRUD + context-event emission.

Coverage:
  G1   Creating a term emits one upsert event (kind=glossary) with the
       scope (space_id) copied over verbatim.
  G2   Updating a term's definition emits another upsert.
  G3   Soft-deleting a term via the repo emits a delete event.
  G4   The unique constraint (space_id, crew_id, term) forbids duplicates
       when all scope columns are set.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import context_events as ce
from src.models.glossary import GlossaryTerm


@pytest_asyncio.fixture
async def event_sink(db_session: AsyncSession):
    from sqlalchemy.orm import Session as SyncSession

    captured: list[ce.ContextEvent] = []
    ce._install_session_hooks(SyncSession)
    ce._register_default_mappings()
    ce.set_publisher(lambda evts: captured.extend(evts))
    try:
        yield captured
    finally:
        ce.set_publisher(None)
        captured.clear()


# ─── G1 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_creating_term_emits_upsert_with_scope(
    db_session: AsyncSession, event_sink: list[ce.ContextEvent]
):
    space_id = uuid.uuid4()
    term = GlossaryTerm(
        term="GMV",
        definition="Gross Merchandise Value — total value of orders placed on the platform.",
        space_id=space_id,
    )
    db_session.add(term)
    await db_session.commit()

    assert len(event_sink) == 1
    evt = event_sink[0]
    assert evt.action == "upsert"
    assert evt.kind == "glossary"
    assert evt.source_table == "glossary_terms"
    assert evt.source_id == str(term.id)
    assert evt.space_id == str(space_id)


# ─── G2 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_updating_term_emits_another_upsert(
    db_session: AsyncSession, event_sink: list[ce.ContextEvent]
):
    term = GlossaryTerm(term="Churn", definition="Rate of customer attrition.")
    db_session.add(term)
    await db_session.commit()
    event_sink.clear()

    term.definition = "Rate of customer attrition per month."
    await db_session.commit()

    assert len(event_sink) == 1
    assert event_sink[0].action == "upsert"
    assert event_sink[0].kind == "glossary"


# ─── G3 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_deleting_term_emits_delete(
    db_session: AsyncSession, event_sink: list[ce.ContextEvent]
):
    term = GlossaryTerm(term="MAU", definition="Monthly Active Users.")
    db_session.add(term)
    await db_session.commit()
    event_sink.clear()

    await db_session.delete(term)
    await db_session.commit()

    assert len(event_sink) == 1
    assert event_sink[0].action == "delete"
    assert event_sink[0].kind == "glossary"


# ─── G4 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_duplicate_term_in_same_scope_rejected(db_session: AsyncSession):
    # NULL values in a unique tuple are not equal to one another — the
    # constraint only bites when every column (including crew_id) has a
    # non-null value. Match that production contract here.
    space_id = uuid.uuid4()
    crew_id = uuid.uuid4()
    a = GlossaryTerm(
        term="ARR", definition="Annual Recurring Revenue.", space_id=space_id, crew_id=crew_id
    )
    b = GlossaryTerm(term="ARR", definition="Duplicate.", space_id=space_id, crew_id=crew_id)
    db_session.add(a)
    await db_session.commit()

    db_session.add(b)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
