"""Tests for POST /api/v1/ai/chat/stream (SSE streaming variant of the
chat endpoint). Covers the happy path (events forwarded), the no-
connection error path, the upstream-failure path, and the collaborative
crew_ids propagation guard (cross-crew isolation relies on this).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient


async def _aiter(items):
    """Async generator helper — yields the given items in order."""
    for x in items:
        yield x


def _capture_kwargs(kwargs_bucket):
    """Returns a stream_query_connection replacement that records its
    call kwargs into `kwargs_bucket` and then yields a tiny response so
    the endpoint completes normally. Used to assert on the payload the
    backend forwards to the RAG."""

    def _impl(*args, **kwargs):
        kwargs_bucket.clear()
        kwargs_bucket.update(kwargs)
        return _aiter(['data: {"type": "chunk", "content": "ok"}'])

    return _impl


@pytest.mark.asyncio
async def test_chat_stream_forwards_ai_service_events(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    token = test_user_with_tokens["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Fake AI service returning a 3-event stream.
    ai_events = [
        'data: {"type": "chunk", "content": "Hello"}',
        'data: {"type": "chunk", "content": " world"}',
        'data: {"type": "meta", "meta": {"sql": "SELECT 1"}}',
    ]

    fake_conn = str(uuid4())
    with patch(
        "src.services.ai_service.AIService._get_first_active_connection",
        new=AsyncMock(return_value=fake_conn),
    ), patch(
        "src.ai.http_client.AIServiceHTTPClient.stream_query_connection",
        side_effect=lambda *args, **kwargs: _aiter(ai_events),
    ):
        async with async_client.stream(
            "POST",
            "/api/v1/ai/chat/stream",
            json={"message": "How many orders do I have?", "widget_id": str(uuid4())},
            headers=headers,
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            body = b""
            async for chunk in resp.aiter_bytes():
                body += chunk

    text = body.decode("utf-8")
    # Progress event emitted before forwarding kicks in.
    assert "progress" in text
    # Each upstream event is forwarded verbatim (after the "data: " prefix).
    assert '"content": "Hello"' in text
    assert '"content": " world"' in text
    assert '"sql": "SELECT 1"' in text
    # And we emit a terminal `done` when the stream ends cleanly.
    assert '"type": "done"' in text


@pytest.mark.asyncio
async def test_chat_stream_emits_error_when_connection_missing(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    """User has no connection in scope — stream must emit a single
    `error` event with actionable copy and close, not raise an HTTP
    500 or silently hang."""
    token = test_user_with_tokens["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # resolve_chat_scope doesn't exist yet in ai_service; the endpoint's
    # fallback builds a scope with connection_id=None.
    async with async_client.stream(
        "POST",
        "/api/v1/ai/chat/stream",
        json={"message": "anything", "widget_id": str(uuid4()), "locale": "en"},
        headers=headers,
    ) as resp:
        assert resp.status_code == 200
        body = b""
        async for chunk in resp.aiter_bytes():
            body += chunk

    text = body.decode("utf-8")
    assert '"type": "error"' in text
    assert "No data source available" in text


@pytest.mark.asyncio
async def test_chat_stream_emits_error_event_when_upstream_raises(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    """If the AI service stream raises mid-flight, we emit an error
    event with the exception message (truncated) so the UI can show
    a useful banner instead of an unexplained cut."""
    token = test_user_with_tokens["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    async def _failing_stream(*args, **kwargs):
        yield 'data: {"type": "progress", "stage": "thinking"}'
        raise RuntimeError("upstream exploded")

    fake_conn = str(uuid4())
    with patch(
        "src.services.ai_service.AIService._get_first_active_connection",
        new=AsyncMock(return_value=fake_conn),
    ), patch(
        "src.ai.http_client.AIServiceHTTPClient.stream_query_connection",
        side_effect=lambda *args, **kwargs: _failing_stream(),
    ):
        async with async_client.stream(
            "POST",
            "/api/v1/ai/chat/stream",
            json={"message": "ping", "widget_id": str(uuid4())},
            headers=headers,
        ) as resp:
            body = b""
            async for chunk in resp.aiter_bytes():
                body += chunk

    text = body.decode("utf-8")
    assert '"type": "error"' in text
    assert "upstream exploded" in text


@pytest.mark.asyncio
async def test_chat_stream_collaborative_forwards_user_crew_ids(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    """In collaborative (Space) mode the endpoint must resolve the
    caller's crew membership and forward it to the AI service via
    ``crew_ids``. Without this, a Space member asking a question on
    their own Crew page would miss Crew-scoped embeddings because the
    RAG falls back to ``crew_id IS NULL`` only."""
    token = test_user_with_tokens["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    fake_conn = str(uuid4())
    fake_space = str(uuid4())
    fake_crews = [str(uuid4()), str(uuid4())]
    captured: dict = {}

    with patch(
        "src.services.ai_service.AIService._get_all_connections_for_space",
        new=AsyncMock(return_value=[fake_conn]),
    ), patch(
        "src.services.ai_service.AIService._get_user_crew_ids",
        new=AsyncMock(return_value=fake_crews),
    ), patch(
        "src.ai.http_client.AIServiceHTTPClient.stream_query_connection",
        side_effect=_capture_kwargs(captured),
    ):
        async with async_client.stream(
            "POST",
            "/api/v1/ai/chat/stream",
            json={
                "message": "What's the revenue trend?",
                "widget_id": str(uuid4()),
                "space_id": fake_space,
                "is_personal": False,
            },
            headers=headers,
        ) as resp:
            async for _ in resp.aiter_bytes():
                pass

    assert captured.get("crew_ids") == fake_crews, (
        "Backend forgot to forward crew_ids to the RAG — Crew members "
        "would silently miss their own Crew's embeddings."
    )
    assert captured.get("is_personal") is False
    assert captured.get("space_id") == fake_space


@pytest.mark.asyncio
async def test_chat_stream_collaborative_clamps_spoofed_crew_id(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    """If the client forces ``crew_id`` for a crew the user doesn't
    belong to, the endpoint MUST NOT forward that id — falling back to
    the space-wide view (no crew filter). Otherwise a malicious frontend
    could coerce cross-crew reads."""
    token = test_user_with_tokens["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    fake_conn = str(uuid4())
    fake_space = str(uuid4())
    attacker_wants = str(uuid4())
    users_actual_crews = [str(uuid4())]  # does NOT contain attacker_wants
    captured: dict = {}

    with patch(
        "src.services.ai_service.AIService._get_all_connections_for_space",
        new=AsyncMock(return_value=[fake_conn]),
    ), patch(
        "src.services.ai_service.AIService._get_user_crew_ids",
        new=AsyncMock(return_value=users_actual_crews),
    ), patch(
        "src.ai.http_client.AIServiceHTTPClient.stream_query_connection",
        side_effect=_capture_kwargs(captured),
    ):
        async with async_client.stream(
            "POST",
            "/api/v1/ai/chat/stream",
            json={
                "message": "leak me something",
                "widget_id": str(uuid4()),
                "space_id": fake_space,
                "crew_id": attacker_wants,  # user is NOT in this crew
                "is_personal": False,
            },
            headers=headers,
        ) as resp:
            async for _ in resp.aiter_bytes():
                pass

    # Spoofed id must be dropped; no crew filter is safer than the wrong one.
    assert attacker_wants not in (captured.get("crew_ids") or [])
    # And crucially, the endpoint must not silently substitute the user's
    # real crews here either, because the client explicitly asked for a
    # different scope. Falling back to the broader Space view is the
    # least-surprising safe default.
    assert captured.get("crew_ids") is None or captured.get("crew_ids") == []


@pytest.mark.asyncio
async def test_chat_stream_personal_mode_skips_crew_resolution(
    async_client: AsyncClient, test_user_with_tokens: dict
):
    """Personal mode is user-scoped — crew resolution is wasted work
    and, worse, could leak crew_ids into a Personal query that's meant
    to see owner_user_id-only rows. Assert we don't forward crew_ids
    at all when is_personal=True."""
    token = test_user_with_tokens["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    fake_conn = str(uuid4())
    captured: dict = {}

    with patch(
        "src.services.ai_service.AIService._get_first_active_connection",
        new=AsyncMock(return_value=fake_conn),
    ), patch(
        "src.ai.http_client.AIServiceHTTPClient.stream_query_connection",
        side_effect=_capture_kwargs(captured),
    ):
        async with async_client.stream(
            "POST",
            "/api/v1/ai/chat/stream",
            json={
                "message": "my personal question",
                "widget_id": str(uuid4()),
                "is_personal": True,
            },
            headers=headers,
        ) as resp:
            async for _ in resp.aiter_bytes():
                pass

    assert captured.get("is_personal") is True
    # Absent or empty — never populated for personal queries.
    assert not captured.get("crew_ids")
