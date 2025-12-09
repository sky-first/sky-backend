"""Celery application configuration."""

import os
from urllib.parse import quote_plus

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


# Get Redis configuration from environment variables (preferred) or settings
redis_host = os.getenv("REDIS_HOST") or getattr(settings, "REDIS_HOST", "redis")
try:
    redis_port = int(os.getenv("REDIS_PORT") or getattr(settings, "REDIS_PORT", 6379))
except (ValueError, TypeError):
    redis_port = 6379
redis_password = os.getenv("REDIS_PASSWORD") or getattr(settings, "REDIS_PASSWORD", "")

# Always build URLs from individual components to ensure proper encoding
broker_url = build_redis_url_from_env(redis_host, redis_port, redis_password, 1)
backend_url = build_redis_url_from_env(redis_host, redis_port, redis_password, 2)

# Debug: Log the URLs (without password for security)
import logging
logger = logging.getLogger(__name__)
logger.info(f"Celery broker URL: redis://:***@{redis_host}:{redis_port}/1")
logger.info(f"Celery backend URL: redis://:***@{redis_host}:{redis_port}/2")

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
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    include=["src.workers.sync_worker", "src.workers.ai_worker"],
)

