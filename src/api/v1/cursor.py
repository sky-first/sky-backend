# Real-time cursor relay via WebSocket — pure in-memory, no DB writes.

import logging
from typing import Dict, List

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from src.core.security import verify_token

router = APIRouter()
logger = logging.getLogger(__name__)


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


# Singleton shared across all workers in the same process.
# For multi-process deployments (gunicorn), replace with Redis Pub/Sub.
cursor_relay = CursorRelay()


@router.websocket("/cursor/{context_id}")
async def cursor_ws(
    websocket: WebSocket,
    context_id: str,
    token: str = Query(..., description="JWT access token"),
) -> None:
    # Validate token and extract user_id
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

    try:
        while True:
            raw = await websocket.receive_text()
            await cursor_relay.relay(context_id, user_id, raw)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("cursor ws error for user %s: %s", user_id, exc)
    finally:
        cursor_relay.disconnect(context_id, user_id)
