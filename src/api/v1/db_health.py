"""Database pool health endpoint — admin-only.

Surfaces SQLAlchemy pool counters + a lightweight ping so the
Administration tab can show whether the API is at risk of pool
saturation. Pairs with the new ``DATABASE_POOL_TIMEOUT`` /
``DATABASE_STATEMENT_TIMEOUT_MS`` / ``DATABASE_PGBOUNCER_MODE``
settings — admins can verify the live values match what's deployed.
"""

from __future__ import annotations

import time
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.config.database import get_connection_pool_stats
from src.config.settings import settings
from src.models.user import User
from src.core.permissions import TENANT_ADMIN_ROLES

router = APIRouter()


class DbHealthResponse(BaseModel):
    ok: bool
    ping_ms: Optional[float] = None
    error: Optional[str] = None
    pool: Dict[str, int]
    config: Dict[str, object]


def _config_snapshot() -> Dict[str, object]:
    """The subset of pool config admins care about for ops debugging.

    Kept stable so ops dashboards can pin against the keys.
    """
    return {
        "pool_size": settings.DATABASE_POOL_SIZE,
        "max_overflow": settings.DATABASE_MAX_OVERFLOW,
        "pool_timeout": settings.DATABASE_POOL_TIMEOUT,
        "pool_pre_ping": settings.DATABASE_POOL_PRE_PING,
        "pool_use_lifo": settings.DATABASE_POOL_USE_LIFO,
        "statement_timeout_ms": settings.DATABASE_STATEMENT_TIMEOUT_MS,
        "idle_in_tx_timeout_ms": settings.DATABASE_IDLE_IN_TX_TIMEOUT_MS,
        "lock_timeout_ms": settings.DATABASE_LOCK_TIMEOUT_MS,
        "pgbouncer_mode": settings.DATABASE_PGBOUNCER_MODE,
    }


@router.get("/", response_model=DbHealthResponse)
async def db_health(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> DbHealthResponse:
    """Admin-only — return pool counters + a SELECT 1 ping."""
    if current_user.role not in TENANT_ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="db health is admin-only",
        )

    try:
        pool_stats: Dict[str, int] = await get_connection_pool_stats()
    except Exception:
        # SQLite tests run without the full pool telemetry; degrade
        # gracefully rather than 500ing the admin panel.
        pool_stats = {}

    try:
        started = time.perf_counter()
        result = await db.execute(text("SELECT 1"))
        result.scalar_one()
        ping_ms = round((time.perf_counter() - started) * 1000.0, 2)
        return DbHealthResponse(
            ok=True,
            ping_ms=ping_ms,
            pool=pool_stats,
            config=_config_snapshot(),
        )
    except Exception as exc:  # pragma: no cover — exercised manually in ops
        return DbHealthResponse(
            ok=False,
            error=str(exc)[:500],
            pool=pool_stats,
            config=_config_snapshot(),
        )
