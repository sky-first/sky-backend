"""Context-row endpoint — pins the bridge between the ingest worker and
the backend that lets user-created entities actually reach the AI.

Without this endpoint, every context event pushed to the Redis stream
was silently dropped by the worker (status=skipped_no_row). These tests
make sure the endpoint stays generic (one registry, every kind works)
and that the serializer returns exactly what the render templates on
the AI side consume: a shallow JSON dict with primitive types.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.context_rows import MODEL_REGISTRY, row_to_dict
from src.models.glossary import GlossaryTerm
from src.models.signal_event import (
    SignalCategory,
    SignalConfidence,
    SignalEvent,
    SignalNature,
)
from src.models.strategy import StrategicPillar


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ─── row_to_dict ──────────────────────────────────────────────────────────


def test_row_to_dict_flattens_uuid_datetime_enum():
    row = SignalEvent(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        category=SignalCategory.EXTERNAL,
        sub_type="competitor_launch",
        nature=SignalNature.EVENT,
        confidence=SignalConfidence.HIGH,
        description="Competitor launched tier 2.",
        start_date=datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
    )

    out = row_to_dict(row)

    assert out["id"] == "11111111-1111-1111-1111-111111111111"
    assert out["category"] == "EXTERNAL"  # enum → value
    assert out["nature"] == "EVENT"
    assert out["confidence"] == "HIGH"
    assert out["sub_type"] == "competitor_launch"
    assert out["description"] == "Competitor launched tier 2."
    # datetime must be ISO, not a raw datetime object that would break json.dumps
    assert isinstance(out["start_date"], str)
    assert "2026-04-01" in out["start_date"]


def test_row_to_dict_handles_none_values():
    pillar = StrategicPillar(
        id=uuid.uuid4(),
        name="Customer Experience",
        description=None,
        color=None,
        space_id=None,
    )

    out = row_to_dict(pillar)

    assert out["name"] == "Customer Experience"
    assert out["description"] is None
    assert out["space_id"] is None


def test_row_to_dict_no_sqlalchemy_internals():
    term = GlossaryTerm(
        id=uuid.uuid4(),
        term="GMV",
        definition="Gross merchandise value.",
    )
    out = row_to_dict(term)
    assert "_sa_instance_state" not in out
    # Only real columns end up in the dict — relationship attributes
    # stay behind because we iterate __table__.columns, not __dict__.
    assert set(out.keys()).issubset({c.name for c in GlossaryTerm.__table__.columns})


# ─── MODEL_REGISTRY ───────────────────────────────────────────────────────


def test_registry_covers_every_context_event_source_table():
    """Every mapping registered in context_events must have a matching
    entry in MODEL_REGISTRY, otherwise the event fires but the ingest
    worker 404s and drops the document.
    """
    # Lazy import to avoid circular registration during collection.
    from src.core import context_events as ce

    ce._register_default_mappings()
    for mapping in ce._mappings.values():
        assert mapping.source_table in MODEL_REGISTRY, (
            f"context_events registered {mapping.source_table} but "
            f"context_rows.MODEL_REGISTRY is missing it — the AI ingest "
            f"worker will 404 on every event of this kind."
        )


# ─── End-to-end HTTP ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_endpoint_returns_row_for_known_table(
    test_user_with_tokens, async_client: AsyncClient, db_session: AsyncSession
):
    term = GlossaryTerm(term="ARR", definition="Annual recurring revenue.")
    db_session.add(term)
    await db_session.commit()
    await db_session.refresh(term)

    resp = await async_client.get(
        f"/api/v1/context/rows/glossary_terms/{term.id}",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["term"] == "ARR"
    assert body["definition"] == "Annual recurring revenue."
    assert body["id"] == str(term.id)


@pytest.mark.asyncio
async def test_endpoint_404s_on_unknown_table(
    test_user_with_tokens, async_client: AsyncClient
):
    resp = await async_client.get(
        f"/api/v1/context/rows/nonsense_table/{uuid.uuid4()}",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == 404
    body = resp.json()
    # The global error middleware wraps FastAPI HTTPExceptions into
    # {"error": {"message": ...}}. Accept either shape so the test is
    # robust if the middleware ever changes.
    detail = body.get("detail") or body.get("error", {}).get("message", "")
    assert "unknown source_table" in detail


@pytest.mark.asyncio
async def test_endpoint_404s_on_missing_row(
    test_user_with_tokens, async_client: AsyncClient
):
    resp = await async_client.get(
        f"/api/v1/context/rows/glossary_terms/{uuid.uuid4()}",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_endpoint_400_on_bad_uuid(
    test_user_with_tokens, async_client: AsyncClient
):
    resp = await async_client.get(
        "/api/v1/context/rows/glossary_terms/not-a-uuid",
        headers=_auth(test_user_with_tokens["access_token"]),
    )
    assert resp.status_code == 400
