"""Real-time crew presence via WebSocket.

Clients connect with:
    ws://<host>/api/v1/presence/<crew_id>?token=<access_token>

Server messages:
    {"type": "presence_init",   "online_user_ids": ["uuid", ...]}
    {"type": "presence_update", "user_id": "uuid", "status": "active|offline"}

Client messages:
    {"type": "ping"}   → server refreshes last_active_at, replies {"type": "pong"}
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Set
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import update

from src.config.database import AsyncSessionLocal
from src.core.security import verify_token
from src.models.user import User
from src.repositories.user import UserRepository

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-memory presence state
# ---------------------------------------------------------------------------


class PresenceManager:
    """Tracks active WebSocket connections keyed by crew_id → user_id → WebSocket."""

    def __init__(self) -> None:
        self._conns: Dict[str, Dict[str, WebSocket]] = {}

    async def connect(self, crew_id: str, user_id: str, ws: WebSocket) -> None:
        await ws.accept()
        if crew_id not in self._conns:
            self._conns[crew_id] = {}
        self._conns[crew_id][user_id] = ws

    def disconnect(self, crew_id: str, user_id: str) -> None:
        crew = self._conns.get(crew_id, {})
        crew.pop(user_id, None)
        if not crew:
            self._conns.pop(crew_id, None)

    def get_online_user_ids(self, crew_id: str) -> Set[str]:
        return set(self._conns.get(crew_id, {}).keys())

    async def broadcast(self, crew_id: str, message: dict) -> None:
        """Broadcast to all connections in a crew, removing dead sockets."""
        dead = []
        for uid, ws in list(self._conns.get(crew_id, {}).items()):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(uid)
        for uid in dead:
            self.disconnect(crew_id, uid)


# Singleton shared across all workers in the same process.
# For multi-process deployments (gunicorn), replace with Redis Pub/Sub.
presence_manager = PresenceManager()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _verify_token_get_user(token: str) -> Optional[User]:
    """Verify an access JWT and return the corresponding User, or None."""
    try:
        payload = verify_token(token, token_type="access")
        user_id = payload.get("sub")
        if not user_id:
            return None
        async with AsyncSessionLocal() as db:
            repo = UserRepository(db)
            return await repo.get_by_id(UUID(user_id))
    except Exception:
        return None


async def _set_user_status(user_id: UUID, status: str) -> None:
    """Persist user online/offline status to the database."""
    try:
        vals: dict = {"status": status}
        if status == "active":
            vals["last_active_at"] = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            await db.execute(update(User).where(User.id == user_id).values(**vals))
            await db.commit()
    except Exception as exc:
        logger.warning("presence._set_user_status(%s, %s) failed: %s", user_id, status, exc)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@router.websocket("/presence/{crew_id}")
async def crew_presence_ws(
    websocket: WebSocket,
    crew_id: str,
    token: str = Query(..., description="JWT access token"),
) -> None:
    """Real-time crew presence WebSocket endpoint."""
    user = await _verify_token_get_user(token)
    if not user:
        await websocket.close(code=4001)
        return

    user_id = str(user.id)

    # Register connection and mark user active
    await presence_manager.connect(crew_id, user_id, websocket)
    await _set_user_status(user.id, "active")

    # Notify all crew members that this user came online
    await presence_manager.broadcast(
        crew_id,
        {
            "type": "presence_update",
            "user_id": user_id,
            "status": "active",
        },
    )

    # Send the new joiner the current online roster
    await websocket.send_json(
        {
            "type": "presence_init",
            "online_user_ids": list(presence_manager.get_online_user_ids(crew_id)),
        }
    )

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await _set_user_status(user.id, "active")
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("presence ws error for user %s: %s", user_id, exc)
    finally:
        presence_manager.disconnect(crew_id, user_id)
        await _set_user_status(user.id, "offline")
        await presence_manager.broadcast(
            crew_id,
            {
                "type": "presence_update",
                "user_id": user_id,
                "status": "offline",
            },
        )
