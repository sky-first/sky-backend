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
from typing import Dict, Set
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import update

from src.models.user import User

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


def _open_session(ctx):
    """Sessão na base do cliente ``ctx``. Costura para os testes.

    Era a ``AsyncSessionLocal`` — a base da PLATAFORMA. Num cliente, o
    utilizador não estava lá, o socket fechava e ninguém aparecia online; e
    o estado era gravado numa linha que não existe.
    """
    from src.config.tenant_connection_manager import tenant_connection_manager

    return tenant_connection_manager.session_for(ctx)


async def authorize_presence_ws(token: str, crew_id: str):
    """``(Admitido, None)`` quando pode ver a presença da equipa; senão
    ``(None, close_code)``.

    Só verificava o token: qualquer pessoa de qualquer cliente via quem está
    online numa equipa cujo id conhecesse — e aparecia online lá. A regra é
    ser MEMBRO da equipa (a linha que dá acesso a uma página de equipa).
    Ver ``ws_access``.
    """
    from src.api.v1.ws_access import autorizar_ws, e_membro_da_equipa

    async def _verificar(db, user) -> bool:
        return await e_membro_da_equipa(db, user, crew_id)

    return await autorizar_ws(
        token,
        _verificar,
        abrir_sessao=lambda ctx: _open_session(ctx),
        rotulo=f"presence ws (crew {crew_id})",
    )


async def _set_user_status(user_id: UUID, status: str, ctx=None) -> None:
    """Persist user online/offline status to the caller's tenant database."""
    from src.core.tenant_context import DEFAULT_TENANT_CONTEXT

    try:
        vals: dict = {"status": status}
        if status == "active":
            vals["last_active_at"] = datetime.now(timezone.utc)
        async with _open_session(ctx or DEFAULT_TENANT_CONTEXT) as db:
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
    admitido, close_code = await authorize_presence_ws(token, crew_id)
    if admitido is None:
        await websocket.close(code=close_code)
        return

    user = admitido.user
    ctx = admitido.ctx
    user_id = admitido.user_id

    # Register connection and mark user active
    await presence_manager.connect(crew_id, user_id, websocket)
    await _set_user_status(user.id, "active", ctx)

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
                await _set_user_status(user.id, "active", ctx)
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("presence ws error for user %s: %s", user_id, exc)
    finally:
        presence_manager.disconnect(crew_id, user_id)
        await _set_user_status(user.id, "offline", ctx)
        await presence_manager.broadcast(
            crew_id,
            {
                "type": "presence_update",
                "user_id": user_id,
                "status": "offline",
            },
        )
