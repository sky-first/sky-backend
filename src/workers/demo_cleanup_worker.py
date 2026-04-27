"""Periodic cleanup of expired public-demo Spaces and guest Users.

Wired into the Celery beat schedule with a daily cadence — see
src/workers/celery_app.py. Idempotent: running it multiple times in
a row only deletes whatever has fallen past its TTL since the last
pass.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="src.workers.demo_cleanup_worker.cleanup_expired_demo_spaces")
def cleanup_expired_demo_spaces_task() -> Dict[str, Any]:
    """Sync entry point Celery beat schedules. Bridges to the async
    cleanup helper inside DemoService.

    Returns a small dict so flower/inspect shows the count per run.
    """
    return asyncio.run(_run())


async def _run() -> Dict[str, Any]:
    # Lazy imports keep the worker process startup light.
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from src.config.settings import settings
    from src.services.demo_service import cleanup_expired_demo_spaces

    # NullPool engine inside this async context — Celery runs each task
    # in its own loop so reusing the global app pool is unsafe (same
    # asyncpg loop-mismatch we hit on the AI service side).
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with SessionLocal() as session:
            spaces, users = await cleanup_expired_demo_spaces(session)
        return {"spaces_deleted": spaces, "users_deleted": users}
    finally:
        await engine.dispose()
