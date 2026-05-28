"""Chat WebSocket relay — page-scoped fanout for chat-threads PR4.

A connection to ``/ws/chat/{page_id}?token=<jwt>`` subscribes the
caller to every server-emitted event on that page:

  - ``message.created``           a new message landed in any thread on
                                  the page (comment, question, ai_response)
  - ``conversation.pinned``       a thread had its pinned_message_id set
  - ``conversation.resolved``     a thread was closed / re-opened
  - ``change_request.created``    a new orange-pill notification
  - ``change_request.resolved``   an accept/dismiss
  - ``widget.created``            a new widget was added to the page
  - ``widget.updated``            a widget was mutated
  - ``widget.deleted``            a widget was removed

Events are JSON envelopes:

  {"type": "message.created", "payload": {...MessageResponse...}}

In multi-process deployments (--workers N) the relay uses Redis
Pub/Sub so events cross process boundaries. Channel name: ``chat:{page_id}``.
Falls back to the in-memory ``ChatRelay`` when Redis is unavailable
(single-worker dev).

This module exposes a singleton ``chat_relay`` (set at startup via
``init_chat_relay``) and a fire-and-forget helper
``broadcast_event_nowait`` used by service-layer code.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from src.core.security import verify_token

router = APIRouter()
logger = logging.getLogger(__name__)


# ─── In-memory relay (single-process / dev fallback) ──────────────────────────

class ChatRelay:
    """Tracks active WebSocket connections keyed by page_id → user_id → list[WebSocket]."""

    def __init__(self) -> None:
        self._conns: Dict[str, Dict[str, List[WebSocket]]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, page_id: str, user_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._conns.setdefault(page_id, {}).setdefault(user_id, []).append(ws)

    async def disconnect(self, page_id: str, user_id: str, ws: WebSocket) -> None:
        async with self._lock:
            sockets = self._conns.get(page_id, {}).get(user_id, [])
            try:
                sockets.remove(ws)
            except ValueError:
                pass
            if not sockets:
                self._conns.get(page_id, {}).pop(user_id, None)
            if not self._conns.get(page_id):
                self._conns.pop(page_id, None)

    async def broadcast(self, page_id: str, event_type: str, payload: Any) -> None:
        message = json.dumps({"type": event_type, "payload": payload}, default=str)
        dead: List[tuple] = []
        for uid, ws_list in list(self._conns.get(page_id, {}).items()):
            for ws in list(ws_list):
                try:
                    await ws.send_text(message)
                except Exception:
                    dead.append((uid, ws))
        for uid, ws in dead:
            await self.disconnect(page_id, uid, ws)

    async def listen(self, page_id: str, user_id: str, ws: WebSocket) -> None:
        # In-memory relay has no separate listen loop — broadcast handles delivery
        # directly. This stub exists so the endpoint can use the same pattern for
        # both relay implementations.
        try:
            await asyncio.Event().wait()  # sleep forever until cancelled
        except asyncio.CancelledError:
            pass


# ─── Redis Pub/Sub relay (multi-process / production) ─────────────────────────

class RedisChatRelay:
    """Pub/Sub relay backed by Redis — works across OS processes."""

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    async def connect(self, page_id: str, user_id: str, ws: WebSocket) -> None:
        await ws.accept()

    async def disconnect(self, page_id: str, user_id: str, ws: WebSocket) -> None:
        pass  # cleanup is handled by the listen task's finally block

    async def broadcast(self, page_id: str, event_type: str, payload: Any) -> None:
        message = json.dumps({"type": event_type, "payload": payload}, default=str)
        await self._redis.publish(f"chat:{page_id}", message)

    async def listen(self, page_id: str, user_id: str, ws: WebSocket) -> None:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(f"chat:{page_id}")
        try:
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    try:
                        await ws.send_text(msg["data"])
                    except Exception:
                        break
        finally:
            await pubsub.unsubscribe(f"chat:{page_id}")
            await pubsub.aclose()


# ─── Module-level singleton — replaced at startup ─────────────────────────────

chat_relay: Any = ChatRelay()


async def init_chat_relay() -> None:
    """Called from the FastAPI lifespan after Redis is initialised.

    Swaps the module-level ``chat_relay`` for a ``RedisChatRelay`` when
    Redis is available, leaving the in-memory fallback in place otherwise.
    """
    global chat_relay
    from src.config.redis import get_redis

    r = await get_redis()
    if r is not None:
        chat_relay = RedisChatRelay(r)
        logger.info("chat_relay: using Redis Pub/Sub")
    else:
        logger.info("chat_relay: Redis unavailable, using in-memory relay")


# ─── Public fire-and-forget helper ────────────────────────────────────────────

def broadcast_event_nowait(page_id: str, event_type: str, payload: Any) -> None:
    """Fire-and-forget broadcast used by sync HTTP service code.

    Wraps the async coroutine in ``create_task`` so the calling endpoint
    returns its response without waiting for every WebSocket peer to ack.
    If there is no running loop (e.g. CLI / sync test path) the call is
    swallowed — chat fanout is best-effort, never load-bearing.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(chat_relay.broadcast(page_id, event_type, payload))


# ─── WebSocket endpoint ───────────────────────────────────────────────────────

@router.websocket("/ws/chat/{page_id}")
async def chat_ws(
    websocket: WebSocket,
    page_id: str,
    token: str = Query(..., description="JWT access token"),
) -> None:
    try:
        payload = verify_token(token, token_type="access")
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=4001)
            return
    except Exception:
        await websocket.close(code=4001)
        return

    await chat_relay.connect(page_id, user_id, websocket)

    listen_task = asyncio.create_task(
        chat_relay.listen(page_id, user_id, websocket)
    )
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("chat ws error for user %s: %s", user_id, exc)
    finally:
        listen_task.cancel()
        try:
            await asyncio.shield(listen_task)
        except (asyncio.CancelledError, Exception):
            pass
        await chat_relay.disconnect(page_id, user_id, websocket)
