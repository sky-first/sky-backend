from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_cache_service_happy_path():
    from src.utils.cache import CacheService

    redis = AsyncMock()
    redis.get = AsyncMock(return_value="v")
    redis.set = AsyncMock()
    redis.delete = AsyncMock(return_value=1)
    redis.keys = AsyncMock(return_value=["k1", "k2"])

    with patch("src.utils.cache.get_redis", AsyncMock(return_value=redis)):
        assert await CacheService.get("k") == "v"

        await CacheService.set("k", "v", ttl=10)
        await CacheService.set("k", {"a": 1})

        await CacheService.delete("k")

        redis.delete = AsyncMock(return_value=2)
        assert await CacheService.delete_pattern("pat*") == 2

        redis.get = AsyncMock(return_value=json.dumps({"a": 1}))
        assert await CacheService.get_json("k") == {"a": 1}

        # empty / None => None
        redis.get = AsyncMock(return_value=None)
        assert await CacheService.get_json("k") is None

        await CacheService.set_json("k", {"b": 2}, ttl=5)


def test_cache_key_helpers():
    from src.utils.cache import (
        connection_metadata_cache_key,
        dashboard_cache_key,
        widget_cache_key,
        workspace_cache_key,
    )

    assert widget_cache_key("1") == "widget:1"
    assert dashboard_cache_key("2") == "dashboard:2"
    assert workspace_cache_key("3") == "workspace:3"
    assert connection_metadata_cache_key("4") == "connection:metadata:4"


@pytest.mark.skip(reason="Brittle DB test in CI")
def test_sync_worker_tasks_smoke():
    from src.workers.sync_worker import sync_connection_metadata

    valid_uuid = "100583e8-99dd-42c7-8e1e-bede4443078d"
    res = sync_connection_metadata.run(valid_uuid)
    assert res["status"] == "success"
    assert str(res["connection_id"]) == valid_uuid


def test_celery_url_helpers():
    from src.workers.celery_app import (
        build_redis_url_from_env,
        encode_password_in_redis_url,
    )

    assert build_redis_url_from_env("redis", 6379, "", 0) == "redis://redis:6379/0"
    assert build_redis_url_from_env("redis", 6379, "p@ss/word", 1).startswith(
        "redis://:"
    )

    # encode_password_in_redis_url should be idempotent
    raw = "redis://:p@ss/word@redis:6379/0"
    encoded = encode_password_in_redis_url(raw)
    assert encode_password_in_redis_url(encoded) == encoded
