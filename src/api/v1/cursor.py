# Real-time cursor relay via WebSocket.
#
# In multi-process deployments (--workers N / multiple K8s replicas) the relay
# uses Redis Pub/Sub so cursor positions cross process boundaries.
#   • Pub/Sub channel: ``cursor:{context_id}``  — live movement fan-out.
#   • State hash:      ``cursors:{context_id}`` — last known cursor per user,
#     so a newly-joined client gets an immediate snapshot of everyone already
#     present (Figma/Liveblocks-style "join sync") instead of having to wait
#     for each peer to move their mouse.
# Falls back to an equivalent in-memory implementation when Redis is absent.
#
# Two correctness guarantees the previous pure-relay version lacked:
#   1. Snapshot-on-join — the server replies with the current cursors the
#      instant a client connects (see ``snapshot``).
#   2. Subscribe-before-read — the connection's Redis subscription is confirmed
#      active *before* we send the snapshot or read any client frame, so no
#      peer update published during the join window is silently dropped
#      (Redis Pub/Sub does not buffer for late subscribers). ``start_listener``
#      only returns once the subscription is live.

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from src.core.security import verify_token

router = APIRouter()
logger = logging.getLogger(__name__)

# TTL (seconds) for a context's cursor state. Clients heartbeat well under
# this (~2s), so a live user's entry stays fresh; a hard-crashed client's
# entry expires instead of haunting future snapshots forever.
CURSOR_STATE_TTL = 60


def _now_ms() -> int:
    return int(time.time() * 1000)


def _leave_payload(user_id: str) -> str:
    """Client-compatible ``leave`` frame. No pageId — the client treats a
    leave as global (drop that user from every page)."""
    return json.dumps({"kind": "leave", "userId": user_id, "ts": _now_ms()})


# ─── In-memory relay (single-process / dev fallback) ──────────────────────────


class CursorRelay:
    """Tracks active connections and last cursor positions, keyed by
    context_id → user_id. Relay is inline, so there is no subscribe race."""

    def __init__(self) -> None:
        self._conns: Dict[str, Dict[str, WebSocket]] = {}
        self._positions: Dict[str, Dict[str, str]] = {}  # ctx -> uid -> raw cursor frame
        self._listen_tasks: Dict[tuple, "asyncio.Task[None]"] = {}

    async def connect(self, context_id: str, user_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._conns.setdefault(context_id, {})[user_id] = ws

    def disconnect(self, context_id: str, user_id: str) -> None:
        ctx = self._conns.get(context_id, {})
        ctx.pop(user_id, None)
        if not ctx:
            self._conns.pop(context_id, None)

    async def listen(
        self,
        context_id: str,
        user_id: str,
        ws: WebSocket,
        ready: Optional[asyncio.Event] = None,
    ) -> None:
        # In-memory relay delivers inline in relay(); the listener just parks
        # until cancelled so the endpoint has a uniform task to cancel on
        # disconnect. There is no subscription, so signal ready immediately.
        if ready is not None:
            ready.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass

    async def start_listener(
        self, context_id: str, user_id: str, ws: WebSocket
    ) -> "asyncio.Task[None]":
        ready = asyncio.Event()
        task = asyncio.create_task(self.listen(context_id, user_id, ws, ready))
        self._listen_tasks[(context_id, user_id)] = task
        await ready.wait()
        return task

    async def snapshot(self, context_id: str, exclude_user_id: str) -> List[Any]:
        out: List[Any] = []
        for uid, raw in self._positions.get(context_id, {}).items():
            if uid == exclude_user_id:
                continue
            try:
                out.append(json.loads(raw))
            except Exception:
                continue
        return out

    def _store(self, context_id: str, user_id: str, raw: str) -> None:
        try:
            obj = json.loads(raw)
        except Exception:
            return
        kind = obj.get("kind")
        if kind == "leave":
            self._positions.get(context_id, {}).pop(user_id, None)
        elif kind == "cursor":
            self._positions.setdefault(context_id, {})[user_id] = raw

    async def relay(self, context_id: str, sender_id: str, raw: str) -> None:
        """Forward raw text to all connections in context except sender, and
        remember the last cursor position for snapshots."""
        self._store(context_id, sender_id, raw)
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
            self._positions.get(context_id, {}).pop(uid, None)

    async def shutdown(self) -> None:
        """Cancel all pending listen tasks — called during app shutdown so the
        event loop can exit cleanly instead of hanging on orphaned tasks."""
        tasks = list(self._listen_tasks.values())
        self._listen_tasks.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def remove(self, context_id: str, user_id: str) -> None:
        """Drop a user on disconnect: clear stored state, tell peers they
        left, and remove the connection."""
        self._listen_tasks.pop((context_id, user_id), None)
        self._positions.get(context_id, {}).pop(user_id, None)
        if not self._positions.get(context_id):
            self._positions.pop(context_id, None)
        leave = _leave_payload(user_id)
        for uid, ws in list(self._conns.get(context_id, {}).items()):
            if uid == user_id:
                continue
            try:
                await ws.send_text(leave)
            except Exception:
                pass
        self.disconnect(context_id, user_id)


# ─── Redis Pub/Sub relay (multi-process / production) ─────────────────────────


class RedisCursorRelay:
    """Pub/Sub relay + ephemeral state hash, backed by Redis — works across
    OS processes and K8s replicas."""

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    @staticmethod
    def _chan(context_id: str) -> str:
        return f"cursor:{context_id}"

    @staticmethod
    def _key(context_id: str) -> str:
        return f"cursors:{context_id}"

    async def connect(self, context_id: str, user_id: str, ws: WebSocket) -> None:
        await ws.accept()

    def disconnect(self, context_id: str, user_id: str) -> None:
        pass  # cleanup is handled by the listen task's finally block + remove()

    async def listen(
        self,
        context_id: str,
        user_id: str,
        ws: WebSocket,
        ready: Optional[asyncio.Event] = None,
    ) -> None:
        pubsub = self._redis.pubsub()
        try:
            await pubsub.subscribe(self._chan(context_id))
        finally:
            # Signal even on failure so start_listener never hangs.
            if ready is not None:
                ready.set()
        try:
            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                try:
                    envelope = json.loads(msg["data"])
                except Exception:
                    continue
                # Do not echo a user's own frames back to them.
                if envelope.get("sender_id") == user_id:
                    continue
                try:
                    await ws.send_text(envelope["data"])
                except Exception:
                    break
        finally:
            try:
                await pubsub.unsubscribe(self._chan(context_id))
                await pubsub.aclose()
            except Exception:
                pass

    async def start_listener(
        self, context_id: str, user_id: str, ws: WebSocket
    ) -> "asyncio.Task[None]":
        """Start the per-connection subscriber and return only once it is
        actually subscribed — closes the subscribe-after-accept race."""
        ready = asyncio.Event()
        task = asyncio.create_task(self.listen(context_id, user_id, ws, ready))
        await ready.wait()
        return task

    async def snapshot(self, context_id: str, exclude_user_id: str) -> List[Any]:
        try:
            raw_map = await self._redis.hgetall(self._key(context_id))
        except Exception:
            return []
        out: List[Any] = []
        for uid, raw in (raw_map or {}).items():
            uid_s = uid.decode() if isinstance(uid, (bytes, bytearray)) else uid
            raw_s = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
            if uid_s == exclude_user_id:
                continue
            try:
                out.append(json.loads(raw_s))
            except Exception:
                continue
        return out

    async def relay(self, context_id: str, sender_id: str, raw: str) -> None:
        await self._store(context_id, sender_id, raw)
        message = json.dumps({"sender_id": sender_id, "data": raw})
        await self._redis.publish(self._chan(context_id), message)

    async def _store(self, context_id: str, user_id: str, raw: str) -> None:
        try:
            obj = json.loads(raw)
        except Exception:
            return
        kind = obj.get("kind")
        key = self._key(context_id)
        try:
            if kind == "leave":
                await self._redis.hdel(key, user_id)
            elif kind == "cursor":
                await self._redis.hset(key, user_id, raw)
                await self._redis.expire(key, CURSOR_STATE_TTL)
        except Exception:
            pass

    async def remove(self, context_id: str, user_id: str) -> None:
        try:
            await self._redis.hdel(self._key(context_id), user_id)
        except Exception:
            pass
        # Broadcast a leave so peers clear our cursor immediately (covers the
        # hard-close case where the client never sent its own leave).
        try:
            envelope = json.dumps({"sender_id": user_id, "data": _leave_payload(user_id)})
            await self._redis.publish(self._chan(context_id), envelope)
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

    # (1) Guarantee our subscription is live BEFORE the snapshot/read loop so
    #     no peer update published during the join window is lost.
    listen_task = await cursor_relay.start_listener(context_id, user_id, websocket)

    # (2) Send the current cursors so peers are visible immediately, without
    #     waiting for them to move.
    try:
        snap = await cursor_relay.snapshot(context_id, exclude_user_id=user_id)
        if snap:
            await websocket.send_text(json.dumps({"kind": "snapshot", "cursors": snap}))
    except Exception as exc:
        logger.debug("cursor snapshot failed for user %s: %s", user_id, exc)

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
        try:
            await cursor_relay.remove(context_id, user_id)
        except Exception:
            pass
