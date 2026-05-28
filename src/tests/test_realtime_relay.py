"""Unit tests for the Redis-backed realtime relay classes.

Covers RedisChatRelay, RedisCursorRelay, init_chat_relay,
init_cursor_relay, and broadcast_event_nowait so coverage stays
above the 63% CI gate after the multi-process relay refactor.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_ws() -> MagicMock:
    ws = MagicMock()
    ws.send_text = AsyncMock()
    ws.accept = AsyncMock()
    return ws


def _make_redis(publish_return: int = 1) -> MagicMock:
    redis = MagicMock()
    redis.publish = AsyncMock(return_value=publish_return)
    return redis


def _make_pubsub(messages: list) -> MagicMock:
    """Build a mock pubsub that yields `messages` then stops."""
    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()

    async def _listen():
        for msg in messages:
            yield msg

    pubsub.listen = _listen
    return pubsub


# ── ChatRelay (in-memory fallback) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_relay_connect_and_broadcast():
    from src.api.v1.chat_ws import ChatRelay

    relay = ChatRelay()
    ws = _make_ws()
    await relay.connect("p1", "u1", ws)
    await relay.broadcast("p1", "message.created", {"content": "hi"})

    ws.send_text.assert_called_once()
    envelope = json.loads(ws.send_text.call_args[0][0])
    assert envelope["type"] == "message.created"
    assert envelope["payload"]["content"] == "hi"


@pytest.mark.asyncio
async def test_chat_relay_disconnect_removes_socket():
    from src.api.v1.chat_ws import ChatRelay

    relay = ChatRelay()
    ws = _make_ws()
    await relay.connect("p1", "u1", ws)
    await relay.disconnect("p1", "u1", ws)
    await relay.broadcast("p1", "any.event", {})
    ws.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_chat_relay_listen_parks_until_cancelled():
    from src.api.v1.chat_ws import ChatRelay

    relay = ChatRelay()
    ws = _make_ws()
    task = asyncio.create_task(relay.listen("p1", "u1", ws))
    await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ── RedisChatRelay ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_redis_chat_relay_broadcast_publishes():
    from src.api.v1.chat_ws import RedisChatRelay

    redis = _make_redis()
    relay = RedisChatRelay(redis)
    await relay.broadcast("p1", "message.created", {"x": 1})

    redis.publish.assert_called_once()
    channel, raw = redis.publish.call_args[0]
    assert channel == "chat:p1"
    msg = json.loads(raw)
    assert msg["type"] == "message.created"
    assert msg["payload"]["x"] == 1


@pytest.mark.asyncio
async def test_redis_chat_relay_connect_accepts_ws():
    from src.api.v1.chat_ws import RedisChatRelay

    redis = _make_redis()
    relay = RedisChatRelay(redis)
    ws = _make_ws()
    await relay.connect("p1", "u1", ws)
    ws.accept.assert_called_once()


@pytest.mark.asyncio
async def test_redis_chat_relay_listen_forwards_messages():
    from src.api.v1.chat_ws import RedisChatRelay

    payload = json.dumps({"type": "message.created", "payload": {"content": "hi"}})
    pubsub = _make_pubsub([
        {"type": "subscribe", "data": 1},   # subscribe ack — must be ignored
        {"type": "message", "data": payload},
    ])
    redis = _make_redis()
    redis.pubsub = MagicMock(return_value=pubsub)

    relay = RedisChatRelay(redis)
    ws = _make_ws()
    await relay.listen("p1", "u1", ws)

    ws.send_text.assert_called_once_with(payload)
    pubsub.unsubscribe.assert_called_once_with("chat:p1")
    pubsub.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_redis_chat_relay_listen_breaks_on_send_error():
    from src.api.v1.chat_ws import RedisChatRelay

    payload = json.dumps({"type": "message.created", "payload": {}})
    pubsub = _make_pubsub([
        {"type": "message", "data": payload},
        {"type": "message", "data": payload},  # second message should not be sent
    ])
    redis = _make_redis()
    redis.pubsub = MagicMock(return_value=pubsub)

    relay = RedisChatRelay(redis)
    ws = _make_ws()
    ws.send_text = AsyncMock(side_effect=Exception("connection closed"))

    await relay.listen("p1", "u1", ws)
    # Should have tried once, then broken out of the loop.
    assert ws.send_text.call_count == 1
    pubsub.aclose.assert_called_once()


# ── CursorRelay (in-memory fallback) ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_cursor_relay_connect_and_relay():
    from src.api.v1.cursor import CursorRelay

    relay = CursorRelay()
    ws_a = _make_ws()
    ws_b = _make_ws()
    await relay.connect("ctx1", "u1", ws_a)
    await relay.connect("ctx1", "u2", ws_b)

    await relay.relay("ctx1", "u1", '{"x":10,"y":20}')

    ws_a.send_text.assert_not_called()          # sender excluded
    ws_b.send_text.assert_called_once_with('{"x":10,"y":20}')


@pytest.mark.asyncio
async def test_cursor_relay_disconnect():
    from src.api.v1.cursor import CursorRelay

    relay = CursorRelay()
    ws = _make_ws()
    await relay.connect("ctx1", "u1", ws)
    relay.disconnect("ctx1", "u1")
    await relay.relay("ctx1", "u2", "data")
    ws.send_text.assert_not_called()


# ── RedisCursorRelay ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_redis_cursor_relay_relay_publishes_envelope():
    from src.api.v1.cursor import RedisCursorRelay

    redis = _make_redis()
    relay = RedisCursorRelay(redis)
    await relay.relay("ctx1", "u1", '{"x":5}')

    redis.publish.assert_called_once()
    channel, raw = redis.publish.call_args[0]
    assert channel == "cursor:ctx1"
    envelope = json.loads(raw)
    assert envelope["sender_id"] == "u1"
    assert envelope["data"] == '{"x":5}'


@pytest.mark.asyncio
async def test_redis_cursor_relay_listen_filters_own_cursor():
    from src.api.v1.cursor import RedisCursorRelay

    own = json.dumps({"sender_id": "u1", "data": '{"x":1}'})
    peer = json.dumps({"sender_id": "u2", "data": '{"x":2}'})
    pubsub = _make_pubsub([
        {"type": "message", "data": own},
        {"type": "message", "data": peer},
    ])
    redis = _make_redis()
    redis.pubsub = MagicMock(return_value=pubsub)

    relay = RedisCursorRelay(redis)
    ws = _make_ws()
    await relay.listen("ctx1", "u1", ws)

    # Only the peer message should be forwarded.
    ws.send_text.assert_called_once_with('{"x":2}')


@pytest.mark.asyncio
async def test_redis_cursor_relay_listen_skips_malformed_json():
    from src.api.v1.cursor import RedisCursorRelay

    pubsub = _make_pubsub([
        {"type": "message", "data": "not-json"},
        {"type": "message", "data": json.dumps({"sender_id": "u2", "data": "ok"})},
    ])
    redis = _make_redis()
    redis.pubsub = MagicMock(return_value=pubsub)

    relay = RedisCursorRelay(redis)
    ws = _make_ws()
    await relay.listen("ctx1", "u1", ws)

    # Malformed message skipped; valid peer message forwarded.
    ws.send_text.assert_called_once_with("ok")


# ── init_chat_relay / init_cursor_relay ───────────────────────────────────────

@pytest.mark.asyncio
async def test_init_chat_relay_uses_redis_when_available():
    from src.api.v1 import chat_ws

    fake_redis = _make_redis()
    with patch("src.config.redis.get_redis", AsyncMock(return_value=fake_redis)):
        await chat_ws.init_chat_relay()

    from src.api.v1.chat_ws import RedisChatRelay
    assert isinstance(chat_ws.chat_relay, RedisChatRelay)

    # Restore to in-memory for test isolation.
    from src.api.v1.chat_ws import ChatRelay
    chat_ws.chat_relay = ChatRelay()


@pytest.mark.asyncio
async def test_init_chat_relay_falls_back_when_redis_none():
    from src.api.v1 import chat_ws
    from src.api.v1.chat_ws import ChatRelay

    with patch("src.config.redis.get_redis", AsyncMock(return_value=None)):
        await chat_ws.init_chat_relay()

    assert isinstance(chat_ws.chat_relay, ChatRelay)


@pytest.mark.asyncio
async def test_init_cursor_relay_uses_redis_when_available():
    from src.api.v1 import cursor

    fake_redis = _make_redis()
    with patch("src.config.redis.get_redis", AsyncMock(return_value=fake_redis)):
        await cursor.init_cursor_relay()

    from src.api.v1.cursor import RedisCursorRelay
    assert isinstance(cursor.cursor_relay, RedisCursorRelay)

    from src.api.v1.cursor import CursorRelay
    cursor.cursor_relay = CursorRelay()


@pytest.mark.asyncio
async def test_init_cursor_relay_falls_back_when_redis_none():
    from src.api.v1 import cursor
    from src.api.v1.cursor import CursorRelay

    with patch("src.config.redis.get_redis", AsyncMock(return_value=None)):
        await cursor.init_cursor_relay()

    assert isinstance(cursor.cursor_relay, CursorRelay)


# ── broadcast_event_nowait ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_broadcast_event_nowait_schedules_task():
    from src.api.v1.chat_ws import ChatRelay, broadcast_event_nowait
    import src.api.v1.chat_ws as chat_ws_mod

    relay = ChatRelay()
    ws = _make_ws()
    await relay.connect("p1", "u1", ws)
    chat_ws_mod.chat_relay = relay

    broadcast_event_nowait("p1", "test.event", {"k": "v"})
    # Give the event loop a chance to run the scheduled task.
    await asyncio.sleep(0)

    ws.send_text.assert_called_once()
    envelope = json.loads(ws.send_text.call_args[0][0])
    assert envelope["type"] == "test.event"
