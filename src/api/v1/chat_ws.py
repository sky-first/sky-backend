"""Chat WebSocket relay — page-scoped fanout for chat-threads PR4.

A connection to ``/ws/chat/{page_id}?token=<jwt>`` subscribes the
caller to every server-emitted event on that page:

  - ``message.created``           a new message landed in any thread on
                                  the page (comment, question, ai_response)
  - ``conversation.pinned``       a thread had its pinned_message_id set
  - ``conversation.resolved``     a thread was closed / re-opened
  - ``change_request.created``    a new orange-pill notification
  - ``change_request.resolved``   an accept/dismiss

Events are JSON envelopes:

  {"type": "message.created", "payload": {...MessageResponse...}}

The relay is **in-memory per process** (same as cursor.py). For
multi-process deployments swap the relay for a Redis Pub/Sub channel
with channel name ``chat:{page_id}``; the public API stays unchanged.

This module exposes a singleton ``chat_relay`` that other services
import to broadcast. The WS endpoint is a thin shell: validate token,
accept, register, sit on receive (the FE doesn't push messages on
this socket — it uses REST for writes), broadcast on disconnect.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from src.core.security import verify_token

router = APIRouter()
logger = logging.getLogger(__name__)


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
        """Push an event to every active connection on `page_id`.

        Synchronous call sites use the create_task helper below so the
        broadcast does not block the HTTP response.
        """
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


# Singleton shared across all workers in the same process. For
# multi-process deployments, replace with Redis Pub/Sub keyed by
# `chat:{page_id}` — see module docstring.
chat_relay = ChatRelay()


def broadcast_event_nowait(page_id: str, event_type: str, payload: Any) -> None:
    """Fire-and-forget broadcast used by sync HTTP service code.

    Wraps the async coroutine in `create_task` so the calling endpoint
    returns its response without waiting for every WebSocket peer to
    ack. If there is no running loop (e.g. CLI / sync test path) we
    swallow the call — chat fanout is best-effort, never load-bearing.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(chat_relay.broadcast(page_id, event_type, payload))


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

    try:
        # FE does NOT push chat messages on this socket — writes go via
        # REST. The receive loop is here only to detect disconnects
        # (FastAPI raises WebSocketDisconnect on close). We discard any
        # text the client happens to send (ping frames, custom keepalive).
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("chat ws error for user %s: %s", user_id, exc)
    finally:
        await chat_relay.disconnect(page_id, user_id, websocket)
