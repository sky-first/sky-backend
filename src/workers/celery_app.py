"""Celery application configuration."""

import logging
import os
from datetime import timedelta
from urllib.parse import quote_plus, unquote_plus

from celery import Celery

from src.config.settings import settings


def build_redis_url_from_env(host: str, port: int, password: str, db: int) -> str:
    """
    Build Redis URL from individual components with proper encoding.

    Args:
        host: Redis host
        port: Redis port
        password: Redis password (will be encoded)
        db: Redis database number

    Returns:
        str: Properly encoded Redis URL
    """
    if password:
        # URL encode the password to handle special characters
        encoded_password = quote_plus(password)
        return f"redis://:{encoded_password}@{host}:{port}/{db}"
    return f"redis://{host}:{port}/{db}"


def encode_password_in_redis_url(url: str) -> str:
    """
    Ensure the password segment in `redis://:password@host/db` is URL-encoded.

    Deploy provides raw passwords containing '/' which breaks URL parsing.
    Kombu expects a valid URL, so we must percent-encode the password in-place.
    """
    if not url or not url.startswith("redis://:") or "@" not in url:
        return url
    try:
        prefix = "redis://:"
        rest = url[len(prefix) :]
        raw_password, host_and_path = rest.rsplit("@", 1)
        # Make encoding idempotent (avoid turning %2F into %252F).
        decoded_password = unquote_plus(raw_password)
        encoded_password = quote_plus(decoded_password)
        return f"{prefix}{encoded_password}@{host_and_path}"
    except Exception:
        return url


# Prefer explicit Celery URLs when provided (Docker Compose sets these on backend).
broker_url = os.getenv("CELERY_BROKER_URL") or ""
backend_url = os.getenv("CELERY_RESULT_BACKEND") or ""

if not broker_url or not backend_url:
    # Fallback: build from Redis components (worker containers set REDIS_HOST/PORT/PASSWORD).
    redis_host = os.getenv("REDIS_HOST") or getattr(settings, "REDIS_HOST", "redis")
    try:
        redis_port = int(os.getenv("REDIS_PORT") or getattr(settings, "REDIS_PORT", 6379))
    except (ValueError, TypeError):
        redis_port = 6379
    redis_password = os.getenv("REDIS_PASSWORD") or getattr(settings, "REDIS_PASSWORD", "")

    # Prefer passing password via transport options, but URL-building is still safe here
    # because this path uses a dedicated REDIS_PASSWORD env (no raw slashes in URL).
    broker_url = broker_url or build_redis_url_from_env(redis_host, redis_port, redis_password, 1)
    backend_url = backend_url or build_redis_url_from_env(redis_host, redis_port, redis_password, 2)

# Always sanitize (encode) env-provided URLs (password may include '/').
broker_url = encode_password_in_redis_url(broker_url)
backend_url = encode_password_in_redis_url(backend_url)

# Celery also reads these env vars internally; override them with safe URLs.
if broker_url:
    os.environ["CELERY_BROKER_URL"] = broker_url
if backend_url:
    os.environ["CELERY_RESULT_BACKEND"] = backend_url

# Debug: Log the URLs (without password for security)
logger = logging.getLogger(__name__)
logger.info("Celery broker URL configured")
logger.info("Celery backend URL configured")

# Initialize Celery with properly encoded URLs
celery_app = Celery(
    "ai_saas_backend",
    broker=broker_url,
    backend=backend_url,
)

# Update configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    task_queues={
        "celery": {"exchange": "celery"},
        "knowledge": {"exchange": "knowledge"},  # dedicated queue, concurrency 4
    },
    task_routes={
        "knowledge.*": {"queue": "knowledge"},
    },
    include=[
        "src.workers.sync_worker",
        "src.workers.ai_worker",
        "src.workers.cache_warming_worker",
        "src.workers.agent_worker",
        "src.workers.insight_agent_worker",
        "src.workers.agent_revocation_worker",
        "src.workers.demo_cleanup_worker",
        "src.workers.knowledge_worker",
    ],
)

# Celery may re-read broker/backend from env vars; force our sanitized URLs.
celery_app.conf.broker_url = broker_url
celery_app.conf.broker_write_url = broker_url
celery_app.conf.result_backend = backend_url

# Periodic tasks (Celery Beat)
try:
    interval = int(getattr(settings, "CACHE_WARMING_INTERVAL_SECONDS", 300) or 300)
    if getattr(settings, "CACHE_WARMING_ENABLED", True) and interval > 0:
        celery_app.conf.beat_schedule = {
            **getattr(celery_app.conf, "beat_schedule", {}),
            "warm-ai-response-cache": {
                "task": "src.workers.cache_warming_worker.warm_ai_response_cache",
                "schedule": timedelta(seconds=interval),
            },
            "schedule-agents": {
                "task": "src.workers.agent_worker.schedule_agents",
                "schedule": timedelta(minutes=5),
            },
            # Insight-mode agents have their own scheduler because they
            # use the new AgentRunService state machine (iteration 1.6)
            # and run at finer granularities (down to 1 minute). Legacy
            # agents stay on the 5-minute beat.
            "schedule-insight-agents": {
                "task": "src.workers.insight_agent_worker.schedule_insight_agents",
                "schedule": timedelta(minutes=1),
            },
            # Agent revocation safety net — every 15 minutes, sweep
            # every ACTIVE agent and pause any whose creator no longer
            # belongs to the agent's scope (HI-002 / W12). Synchronous
            # hook in space/crew remove_member is best-effort; this is
            # the guarantee of eventual consistency.
            "sweep-orphan-agents": {
                "task": "src.workers.agent_revocation_worker.sweep_orphan_agents",
                "schedule": timedelta(minutes=15),
            },
            # Public demo (Cenário B) sandbox cleanup. Daily pass deletes
            # any Space/User past its TTL — keeps the table small and
            # protects against vandalism living on the public surface
            # for more than the advertised window.
            "cleanup-expired-demo-spaces": {
                "task": "src.workers.demo_cleanup_worker.cleanup_expired_demo_spaces",
                "schedule": timedelta(hours=24),
            },
        }
except Exception:
    # Fail-open: do not block worker startup if schedule can't be built.
    pass
