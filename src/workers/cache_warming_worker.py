"""Background cache warming tasks (Celery).

Subtask 2: scheduler/worker that warms the short-lived AI response cache.
"""

import asyncio
import logging
from typing import Any, Dict, Optional

from src.ai.real_service import RealAIService
from src.config.settings import settings
from src.services.ai_service import AIService
from src.services.cache_warming_service import get_ai_cache_warm_candidates
from src.utils.cache import CacheService, ai_response_cache_key
from src.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=0)
def warm_ai_response_cache(self) -> Dict[str, Any]:
    """
    Periodic task that warms the AI response cache for the most frequent recent questions.

    Fail-open: if Redis/AI is unavailable, we log and exit without raising.
    """
    try:
        return asyncio.run(_warm_ai_response_cache_async())
    except Exception as exc:
        logger.error("Cache warming task crashed", exc_info=True)
        # Don't retry automatically; failures are typically transient and will be retried by schedule.
        return {"status": "error", "error": str(exc)}


async def _warm_ai_response_cache_async() -> Dict[str, Any]:
    # Only makes sense when caching is enabled and real AI is configured.
    if getattr(settings, "AI_RESPONSE_CACHE_TTL_SECONDS", 0) <= 0:
        return {"status": "skipped", "reason": "AI_RESPONSE_CACHE_TTL_SECONDS <= 0"}
    if settings.AI_SERVICE_TYPE != "real":
        return {"status": "skipped", "reason": "AI_SERVICE_TYPE != real"}
    if not (getattr(settings, "REDIS_URL", "") or ""):
        return {"status": "skipped", "reason": "REDIS_URL not configured"}
    if not getattr(settings, "CACHE_WARMING_ENABLED", True):
        return {"status": "skipped", "reason": "CACHE_WARMING_ENABLED is false"}

    # Import models so SQLAlchemy relationship targets resolve (worker doesn't import the whole app).
    import src.models  # noqa: F401
    from src.config.database import AsyncSessionLocal

    max_warms = int(getattr(settings, "CACHE_WARMING_MAX_WARMS_PER_RUN", 50) or 50)
    lookback_hours = int(getattr(settings, "CACHE_WARMING_LOOKBACK_HOURS", 24) or 24)
    top_n = int(getattr(settings, "CACHE_WARMING_TOP_N_PER_CONNECTION", 10) or 10)
    max_scan = int(getattr(settings, "CACHE_WARMING_MAX_SCAN_ROWS", 5000) or 5000)
    max_total = int(getattr(settings, "CACHE_WARMING_MAX_TOTAL_CANDIDATES", 200) or 200)

    hits = 0
    misses = 0
    warmed = 0
    skipped = 0
    errors = 0

    real_ai = RealAIService()

    async with AsyncSessionLocal() as db:
        candidates = await get_ai_cache_warm_candidates(
            db,
            lookback_hours=lookback_hours,
            top_n_per_connection=top_n,
            max_scan_rows=max_scan,
            max_total=max_total,
        )

        if not candidates:
            return {
                "status": "ok",
                "candidates": 0,
                "hits": 0,
                "misses": 0,
                "warmed": 0,
                "skipped": 0,
                "errors": 0,
            }

        ai_service = AIService(db)

        for c in candidates:
            if warmed >= max_warms:
                break

            cache_key = ai_response_cache_key(
                space_id=c.space_id,
                connection_id=c.connection_id,
                question=c.question,
            )

            try:
                existing = await CacheService.get_json(cache_key)
                if existing:
                    hits += 1
                    continue
                misses += 1

                # Resolve crew_ids for context (best-effort).
                crew_ids = None
                try:
                    crew_ids = await ai_service._get_user_crew_ids(  # noqa: SLF001
                        c.user_id,
                        c.space_id,
                        all_spaces=False,
                    )
                except Exception:
                    crew_ids = None

                # Execute the query via Real AI Service and cache result.
                thread_id = f"warm:{c.space_id}:{c.connection_id}:{cache_key[-12:]}"
                result = await real_ai.process_query(
                    connection_id=c.connection_id,
                    question=c.question,
                    user_id=str(c.user_id),
                    space_id=c.space_id,
                    crew_ids=crew_ids if crew_ids else None,
                    thread_id=thread_id,
                    is_personal=False,
                    selected_datasets=None,
                    instructions=None,
                )

                payload: Dict[str, Any] = {
                    "answer": result.get("answer", ""),
                    "data_sample": result.get("data_sample", []),
                    "sql": result.get("sql"),
                    "chosen_table": result.get("chosen_table"),
                    "chosen_datasets": result.get("chosen_datasets", []),
                    "title": result.get("title"),
                    "detected_language": result.get("detected_language"),
                    "meta": result.get("meta"),
                }

                await CacheService.set_json(
                    cache_key,
                    payload,
                    ttl=settings.AI_RESPONSE_CACHE_TTL_SECONDS,
                )
                warmed += 1
            except Exception as e:
                errors += 1
                logger.warning(
                    "Cache warming failed for candidate",
                    extra={
                        "space_id": c.space_id,
                        "connection_id": c.connection_id,
                        "question": c.question[:200],
                        "error": str(e),
                    },
                    exc_info=True,
                )
                continue

    return {
        "status": "ok",
        "candidates": len(candidates),
        "hits": hits,
        "misses": misses,
        "warmed": warmed,
        "skipped": skipped,
        "errors": errors,
        "max_warms": max_warms,
    }
