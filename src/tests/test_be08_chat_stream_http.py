"""BE-08 · Chat SSE — endpoint-level acceptance (G8).

Contract shape (types, citations, error code) is unit-tested in
test_chat_stream_contract.py; here we exercise the real POST /ai/chat/stream:
ordered sequence (T-08.1), insight-scoped context (T-08.3), abort cleanup
(T-08.4), no-buffering (T-08.6) and scope forwarding / isolation (T-08.7).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.tests.acceptance_helpers import bearer

_CONN = "src.services.ai_service.AIService._get_first_active_connection"
_STREAM = "src.ai.http_client.AIServiceHTTPClient.stream_query_connection"


async def _aiter(items):
    for x in items:
        yield x


def _events(body: str):
    """Parse SSE ``data:`` frames into event dicts (ignoring `: keepalive`)."""
    out = []
    for block in body.split("\n\n"):
        block = block.strip()
        if block.startswith("data:"):
            try:
                out.append(json.loads(block[len("data:") :].strip()))
            except json.JSONDecodeError:
                pass
    return out


async def _drain(async_client, headers, payload, stream_impl):
    with (
        patch(_CONN, new=AsyncMock(return_value=str(uuid4()))),
        patch(_STREAM, side_effect=stream_impl),
    ):
        async with async_client.stream(
            "POST", "/api/v1/ai/chat/stream", json=payload, headers=headers
        ) as resp:
            assert resp.status_code == 200
            body = ""
            async for chunk in resp.aiter_text():
                body += chunk
    return body


# ─── T-08.1 · ordered progress → chunk* → meta → done ───────────────────────
# ─── T-08.6 · chunks arrive as separate frames (no buffering) ───────────────
@pytest.mark.asyncio
async def test_t08_1_ordered_sequence_and_no_buffering(async_client, test_user_with_tokens):
    engine = [
        'data: {"type": "progress", "stage": "specialist", "message": "..."}',
        'data: {"type": "chunk", "content": "Rev "}',
        'data: {"type": "chunk", "content": "up 18%"}',
        'data: {"type": "meta", "meta": {"detected_language": "en"}, "data_sample": []}',
        'data: {"type": "sql_generated", "sql": "SELECT 1"}',  # debug → dropped
        'data: {"type": "done"}',  # engine done → dropped (backend owns it)
    ]
    body = await _drain(
        async_client,
        bearer(test_user_with_tokens["access_token"]),
        {"message": "why up?", "widget_id": str(uuid4())},
        lambda *a, **k: _aiter(engine),
    )
    types = [e["type"] for e in _events(body)]
    # backend's own 'starting' progress + the engine's progress, then the two
    # chunks kept SEPARATE (no buffering), meta, and the backend's single done.
    # The debug sql_generated and the engine's own done are dropped.
    assert types == ["progress", "progress", "chunk", "chunk", "meta", "done"]
    assert "sql_generated" not in types and types.count("done") == 1


# ─── T-08.3 · "Ask Sky about this" scopes the answer to the insight ─────────
@pytest.mark.asyncio
async def test_t08_3_insight_context_injected(
    async_client, test_user, test_user_with_tokens, db_session
):
    from src.models.agent import AgentFinding
    from src.models.space import SpaceMember

    space = uuid4()
    db_session.add(SpaceMember(user_id=test_user["user"].id, space_id=space, role="member"))
    finding = AgentFinding(
        agent_id=None,
        source="scan",
        space_id=space,
        agent_name="Autonomous scan",
        type="risk",
        severity="high",
        title="North sales down",
        description="down 18% WoW",
        series=[],
        stat_tiles=[],
        viz_kind="big_number",
    )
    db_session.add(finding)
    await db_session.commit()
    await db_session.refresh(finding)

    captured: dict = {}

    def _capture(*a, **k):
        captured.update(k)
        return _aiter(['data: {"type": "chunk", "content": "ok"}'])

    await _drain(
        async_client,
        bearer(test_user_with_tokens["access_token"]),
        {
            "message": "why?",
            "widget_id": str(uuid4()),
            "context": {"insight_id": str(finding.id)},
        },
        _capture,
    )
    assert "North sales down" in (captured.get("instructions") or "")


# ─── T-08.7 · the backend forwards the caller's scope (isolation) ───────────
@pytest.mark.asyncio
async def test_t08_7_scope_forwarded_to_engine(async_client, test_user, test_user_with_tokens):
    captured: dict = {}

    def _capture(*a, **k):
        captured.update(k)
        return _aiter(['data: {"type": "chunk", "content": "ok"}'])

    await _drain(
        async_client,
        bearer(test_user_with_tokens["access_token"]),
        {"message": "list every table", "widget_id": str(uuid4())},
        _capture,
    )
    # The engine is called with the CALLER's resolved identity/scope — a device
    # can't widen it, so answers stay within the caller's authorized surface.
    assert captured.get("user_id") == str(test_user["user"].id)
    assert "crew_ids" in captured  # scope is always passed (may be None)


# ─── T-08.4 · aborting the stream closes the upstream (no leaked worker) ────
@pytest.mark.asyncio
async def test_t08_4_abort_closes_upstream():
    from src.schemas.chat_stream import with_heartbeat

    closed = {"v": False}

    async def _source():
        try:
            yield "data: a\n\n"
            yield "data: b\n\n"
        finally:
            closed["v"] = True  # runs when the generator is closed

    gen = with_heartbeat(_source(), interval_seconds=5)
    assert await gen.__anext__() == "data: a\n\n"
    await gen.aclose()  # client disconnects mid-stream
    assert closed["v"] is True  # upstream was released — nothing leaks
