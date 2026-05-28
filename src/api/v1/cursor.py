# Real-time cursor relay via WebSocket.
#
# In multi-process deployments (--workers N) the relay uses Redis Pub/Sub
# so cursor positions cross process boundaries. Channel: ``cursor:{context_id}``.
# Falls back to in-memory when Redis is unavailable.

import asyncio
import json
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from src.core.security import verify_token

router = APIRouter()
logger = logging.getLogger(__name__)


# ─── In-memory relay (single-process / dev fallback) ──────────────────────────

class CursorRelay:
    """Tracks active WebSocket connections keyed by context_id → user_id → WebSocket."""

    def __init__(self) -> None:
        self._conns: Dict[str, Dict[str, WebSocket]] = {}

    async def connect(self, context_id: str, user_id: str, ws: WebSocket) -> None:
        await ws.accept()
        if context_id not in self._conns:
            self._conns[context_id] = {}
        self._conns[context_id][user_id] = ws

    def disconnect(self, context_id: str, user_id: str) -> None:
        ctx = self._conns.get(context_id, {})
        ctx.pop(user_id, None)
        if not ctx:
            self._conns.pop(context_id, None)

    async def relay(self, context_id: str, sender_id: str, raw: str) -> None:
        """Forward raw text to all connections in context except sender."""
        dead: List[str] = []
        for uid, ws in list(self._conns.get(context_id, {}).items()):
            if uid == sender_id:
                continue
            try:
                await ws.send_text(raw)
            except Exception:
                dead.append(uid)
        for uid in dead:
            self.disconnect(context_id, uid)

    async def listen(self, context_id: str, user_id: str, ws: WebSocket) -> None:
        # In-memory relay: relay() is called inline in the receive loop, so
        # the listen task just parks here until cancelled.
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass


# ─── Redis Pub/Sub relay (multi-process / production) ─────────────────────────

class RedisCursorRelay:
    """Pub/Sub relay backed by Redis — works across OS processes."""

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    async def connect(self, context_id: str, user_id: str, ws: WebSocket) -> None:
        await ws.accept()

    def disconnect(self, context_id: str, user_id: str) -> None:
        pass  # cleanup is handled by the listen task's finally block

    async def relay(self, context_id: str, sender_id: str, raw: str) -> None:
        message = json.dumps({"sender_id": sender_id, "data": raw})
        await self._redis.publish(f"cursor:{context_id}", message)

    async def listen(self, context_id: str, user_id: str, ws: WebSocket) -> None:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(f"cursor:{context_id}")
        try:
            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                try:
                    envelope = json.loads(msg["data"])
                except Exception:
                    continue
                # Do not echo the sender's own cursor back to them
                if envelope.get("sender_id") == user_id:
                    continue
                try:
                    await ws.send_text(envelope["data"])
                except Exception:
                    break
        finally:
            try:
                await pubsub.unsubscribe(f"cursor:{context_id}")
                await pubsub.aclose()
            except Exception:
                pass


# ─── Module-level singleton — replaced at startup ─────────────────────────────

cursor_relay: Any = CursorRelay()


async def init_cursor_relay() -> None:
    """Called from the FastAPI lifespan after Redis is initialised.

    Swaps the module-level ``cursor_relay`` for a ``RedisCursorRelay`` when
    Redis is available, leaving the in-memory fallback in place otherwise.
    """
    global cursor_relay
    from src.config.redis import get_redis

    r = await get_redis()
    if r is not None:
        cursor_relay = RedisCursorRelay(r)
        logger.info("cursor_relay: using Redis Pub/Sub")
    else:
        logger.info("cursor_relay: Redis unavailable, using in-memory relay")


# ─── WebSocket endpoint ───────────────────────────────────────────────────────

@router.websocket("/cursor/{context_id}")
async def cursor_ws(
    websocket: WebSocket,
    context_id: str,
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

    await cursor_relay.connect(context_id, user_id, websocket)

    listen_task = asyncio.create_task(
        cursor_relay.listen(context_id, user_id, websocket)
    )
    try:
        while True:
            raw = await websocket.receive_text()
            await cursor_relay.relay(context_id, user_id, raw)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("cursor ws error for user %s: %s", user_id, exc)
    finally:
        listen_task.cancel()
        try:
            await listen_task
        except (asyncio.CancelledError, Exception):
            pass
        cursor_relay.disconnect(context_id, user_id)
