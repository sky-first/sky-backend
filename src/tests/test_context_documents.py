"""Tests for the ContextDocument model + repository — Phase 2.1.

Covers the acceptance surface of the Context Layer foundation:

  C1   upsert by (source_table, source_id) creates a new row
  C2   upsert on the same (source_table, source_id) updates in place,
       clears indexed_at so the ingest worker re-embeds
  C3   kind check-constraint rejects unknown kinds
  C4   visibility check-constraint rejects unknown visibility levels
  C5   uniqueness on (source_table, source_id) prevents duplicates
  C6   soft_delete marks deleted_at; row still readable with include_deleted
  C7   list_in_scope filters by space / crew / kind and hides deleted by default

The embedding column is not exercised here — pgvector is not available in
the SQLite test bed. §3.6 of the master plan documents the AI-service
write path for embeddings.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.context_document import ContextDocument, ContextDocumentKind
from src.repositories.context_document import ContextDocumentRepository


def _uuid():
    return uuid.uuid4()


# ─── C1 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_upsert_creates_new_document(db_session: AsyncSession):
    repo = ContextDocumentRepository(db_session)
    src = _uuid()

    doc = await repo.upsert(
        kind=ContextDocumentKind.GOAL.value,
        source_table="strategy_goals",
        source_id=src,
        title="Increase ARR by 20%",
        body="Owner: CFO. Target: +20% ARR by Q4.",
        metadata={"owner": "cfo", "pillar": "growth"},
        visibility="space",
    )
    await db_session.commit()

    assert doc.id is not None
    assert doc.kind == "goal"
    assert doc.source_table == "strategy_goals"
    assert str(doc.source_id) == str(src)
    assert doc.indexed_at is None, "new doc must not be pre-indexed"
    assert doc.deleted_at is None


# ─── C2 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_upsert_updates_in_place_and_resets_indexed_at(
    db_session: AsyncSession,
):
    repo = ContextDocumentRepository(db_session)
    src = _uuid()

    first = await repo.upsert(
        kind=ContextDocumentKind.GOAL.value,
        source_table="strategy_goals",
        source_id=src,
        title="Initial title",
        body="Initial body",
    )
    # Simulate the AI service having indexed the row.
    from datetime import datetime

    first.indexed_at = datetime.utcnow()
    await db_session.commit()

    second = await repo.upsert(
        kind=ContextDocumentKind.GOAL.value,
        source_table="strategy_goals",
        source_id=src,
        title="Updated title",
        body="Updated body",
    )
    await db_session.commit()

    assert second.id == first.id, "same row, not a duplicate"
    assert second.title == "Updated title"
    assert second.indexed_at is None, "update must clear indexed_at so the worker re-embeds"


# ─── C3 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_unknown_kind_is_rejected_by_check_constraint(
    db_session: AsyncSession,
):
    doc = ContextDocument(
        kind="totally_made_up_kind",
        source_table="x",
        source_id=_uuid(),
        title="x",
        body="x",
    )
    db_session.add(doc)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ─── C4 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_unknown_visibility_is_rejected(db_session: AsyncSession):
    doc = ContextDocument(
        kind=ContextDocumentKind.GOAL.value,
        source_table="strategy_goals",
        source_id=_uuid(),
        title="x",
        body="x",
        visibility="galaxy",  # not in {public,space,crew,user}
    )
    db_session.add(doc)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ─── C5 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_duplicate_source_rejected(db_session: AsyncSession):
    repo = ContextDocumentRepository(db_session)
    src = _uuid()
    await repo.upsert(
        kind=ContextDocumentKind.GOAL.value,
        source_table="strategy_goals",
        source_id=src,
        title="a",
        body="a",
    )
    await db_session.commit()

    # A raw second insert at the model level must hit the unique index.
    dup = ContextDocument(
        kind=ContextDocumentKind.GOAL.value,
        source_table="strategy_goals",
        source_id=src,
        title="b",
        body="b",
    )
    db_session.add(dup)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ─── C6 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_soft_delete_hides_from_default_list(db_session: AsyncSession):
    repo = ContextDocumentRepository(db_session)
    src = _uuid()
    await repo.upsert(
        kind=ContextDocumentKind.GOAL.value,
        source_table="strategy_goals",
        source_id=src,
        title="Doomed",
        body="...",
    )
    await db_session.commit()

    ok = await repo.soft_delete_by_source("strategy_goals", src)
    await db_session.commit()
    assert ok is True

    alive = await repo.list_in_scope(kind="goal")
    assert not any(str(d.source_id) == str(src) for d in alive)

    with_deleted = await repo.list_in_scope(kind="goal", include_deleted=True)
    assert any(str(d.source_id) == str(src) for d in with_deleted)


# ─── C7 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_list_in_scope_filters_by_space_crew_and_kind(
    db_session: AsyncSession,
):
    repo = ContextDocumentRepository(db_session)
    space_a, space_b = _uuid(), _uuid()
    crew_a = _uuid()

    await repo.upsert(
        kind=ContextDocumentKind.GOAL.value,
        source_table="strategy_goals",
        source_id=_uuid(),
        title="GoalA-space",
        body="...",
        space_id=space_a,
    )
    await repo.upsert(
        kind=ContextDocumentKind.OKR.value,
        source_table="strategy_okrs",
        source_id=_uuid(),
        title="OkrA-space",
        body="...",
        space_id=space_a,
    )
    await repo.upsert(
        kind=ContextDocumentKind.GOAL.value,
        source_table="strategy_goals",
        source_id=_uuid(),
        title="GoalB-space",
        body="...",
        space_id=space_b,
    )
    await repo.upsert(
        kind=ContextDocumentKind.GOAL.value,
        source_table="strategy_goals",
        source_id=_uuid(),
        title="GoalA-crew",
        body="...",
        space_id=space_a,
        crew_id=crew_a,
    )
    await db_session.commit()

    only_space_a = await repo.list_in_scope(space_id=space_a)
    assert len(only_space_a) == 3
    assert all(str(d.space_id) == str(space_a) for d in only_space_a)

    only_goals_in_a = await repo.list_in_scope(space_id=space_a, kind="goal")
    assert len(only_goals_in_a) == 2

    only_crew_a = await repo.list_in_scope(crew_id=crew_a)
    assert len(only_crew_a) == 1
    assert only_crew_a[0].title == "GoalA-crew"
