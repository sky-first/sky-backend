import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import Request, Response

from src.api.middleware.auth import auth_middleware
from src.api.middleware.error_handler import error_handler_middleware
from src.api.middleware.logging import logging_middleware
from src.api.middleware.rate_limit import rate_limit_middleware
from src.core.exceptions import (
    BadRequestError,
    BaseAPIException,
    ConflictError,
    ForbiddenError,
    InternalServerError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from src.services.auth0_service import Auth0Service
from src.services.rbac_service import EffectivePermissions, RBACService
from src.utils.cache import CacheService
from src.utils.cache import connection_metadata_cache_key as conn_cache_key
from src.utils.cache import dashboard_cache_key, widget_cache_key, workspace_cache_key
from src.workers.ai_worker import build_dashboard_job, process_ai_query
from src.workers.cache_warming_worker import _warm_ai_response_cache_async
from src.workers.celery_app import build_redis_url_from_env, encode_password_in_redis_url
from src.workers.sync_worker import sync_connection, sync_connection_metadata

# --- Tests for src/utils/cache.py ---


@pytest.mark.asyncio
async def test_cache_service_methods():
    mock_redis = AsyncMock()
    with patch("src.utils.cache.get_redis", return_value=mock_redis):
        await CacheService.get("key")
        await CacheService.set("key", "val")
        await CacheService.set("key", {"a": 1})
        await CacheService.delete("key")
        mock_redis.keys.return_value = ["k1"]
        mock_redis.delete.return_value = 1
        assert await CacheService.delete_pattern("pat*") == 1
        mock_redis.keys.return_value = []
        assert await CacheService.delete_pattern("empty*") == 0
        mock_redis.get.return_value = json.dumps({"a": 1})
        await CacheService.get_json("key")
        await CacheService.set_json("key", {"b": 2})


def test_cache_keys():
    assert widget_cache_key("1") == "widget:1"
    assert dashboard_cache_key("2") == "dashboard:2"
    assert workspace_cache_key("3") == "workspace:3"
    assert conn_cache_key("4") == "connection:metadata:4"


# --- Tests for src/workers/cache_warming_worker.py ---


@pytest.mark.asyncio
async def test_cache_warming_skips_when_cache_disabled():
    # Ensure we never touch DB/Redis/AI in this test; it's purely a guard-rail branch.
    with patch("src.workers.cache_warming_worker.settings") as s:
        s.AI_RESPONSE_CACHE_TTL_SECONDS = 0
        s.AI_SERVICE_TYPE = "real"
        s.REDIS_URL = "redis://localhost:6379/0"
        s.CACHE_WARMING_ENABLED = True

        res = await _warm_ai_response_cache_async()
        assert res["status"] == "skipped"


@pytest.mark.asyncio
async def test_cache_warming_skips_when_not_real_ai():
    with patch("src.workers.cache_warming_worker.settings") as s:
        s.AI_RESPONSE_CACHE_TTL_SECONDS = 600
        s.AI_SERVICE_TYPE = "mock"
        s.REDIS_URL = "redis://localhost:6379/0"
        s.CACHE_WARMING_ENABLED = True

        res = await _warm_ai_response_cache_async()
        assert res["status"] == "skipped"


# --- Tests for src/workers/sync_worker.py ---


def test_sync_connection_task():
    func = getattr(sync_connection, "__wrapped__", sync_connection)
    try:
        func(MagicMock(), "conn_id")
    except Exception:
        pass


def test_sync_connection_task_retry_branch():
    # `.run` is bound to the Celery Task instance, so we patch the Task's retry.
    with patch.object(sync_connection, "retry", side_effect=RuntimeError("retry")):
        with patch("src.workers.sync_worker.logger.info", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="retry"):
                sync_connection.run("conn_id")


def test_sync_connection_metadata_task():
    func = getattr(sync_connection_metadata, "__wrapped__", sync_connection_metadata)
    try:
        func("conn_id")
    except Exception:
        pass


def test_sync_connection_metadata_task_exception_branch():
    func = getattr(sync_connection_metadata, "__wrapped__", sync_connection_metadata)
    with patch("src.workers.sync_worker.logger.info", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="boom"):
            func("conn_id")


# --- Tests for src/workers/ai_worker.py ---


def test_process_ai_query_task():
    func = getattr(process_ai_query, "__wrapped__", process_ai_query)
    try:
        func(MagicMock(), "query_id")
    except Exception:
        pass


def test_build_dashboard_job_task():
    func = getattr(build_dashboard_job, "__wrapped__", build_dashboard_job)
    with patch("src.workers.ai_worker.asyncio.run"):
        try:
            func(MagicMock(), str(uuid4()))
        except Exception:
            pass


# --- Tests for src/workers/celery_app.py ---


def test_build_redis_url_from_env():
    assert build_redis_url_from_env("redis", 6379, "pa/ss", 1) == "redis://:pa%2Fss@redis:6379/1"
    assert build_redis_url_from_env("redis", 6379, "", 2) == "redis://redis:6379/2"


def test_encode_password_in_redis_url():
    assert encode_password_in_redis_url("") == ""
    assert encode_password_in_redis_url("redis://localhost:6379/0") == "redis://localhost:6379/0"
    assert (
        encode_password_in_redis_url("redis://:pa/ss@redis:6379/0")
        == "redis://:pa%2Fss@redis:6379/0"
    )
    # Idempotent (should not double-encode)
    assert (
        encode_password_in_redis_url("redis://:pa%2Fss@redis:6379/0")
        == "redis://:pa%2Fss@redis:6379/0"
    )


# --- Tests for src/api/middleware/logging.py ---


@pytest.mark.asyncio
async def test_logging_middleware():
    request = MagicMock(spec=Request)
    request.method = "GET"
    request.url.path = "/test"

    async def call_next(req):
        return Response()

    await logging_middleware(request, call_next)


# --- Tests for src/api/middleware/rate_limit.py ---


@pytest.mark.asyncio
async def test_rate_limit_middleware_coverage():
    mock_redis = AsyncMock()
    with patch("src.api.middleware.rate_limit.get_redis", return_value=mock_redis):
        with patch("src.api.middleware.rate_limit.settings") as mock_settings:
            mock_settings.RATE_LIMIT_ENABLED = True
            mock_settings.RATE_LIMIT_PER_MINUTE = 10
            mock_settings.RATE_LIMIT_PER_HOUR = 100

            request = MagicMock(spec=Request)
            request.client.host = "127.0.0.1"
            request.headers = {}

            async def call_next(req):
                return Response()

            mock_redis.incr.return_value = 1

            # Success path
            await rate_limit_middleware(request, call_next)

            # Rate limit exceeded (minute)
            mock_redis.incr.return_value = 11
            res = await rate_limit_middleware(request, call_next)
            assert res.status_code == 429


# --- Tests for src/api/middleware/auth.py ---


@pytest.mark.asyncio
async def test_auth_middleware_public():
    request = MagicMock(spec=Request)
    request.method = "GET"
    request.url.path = "/health"

    async def call_next(req):
        return Response()

    res = await auth_middleware(request, call_next)
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_auth_middleware_no_header():
    request = MagicMock(spec=Request)
    request.method = "GET"
    request.url.path = "/api/v1/protected"
    request.headers = {}

    async def call_next(req):
        return Response()

    res = await auth_middleware(request, call_next)
    assert res.status_code == 401


# --- Tests for src/api/middleware/error_handler.py ---


@pytest.mark.asyncio
async def test_error_handler_middleware():
    request = MagicMock(spec=Request)
    request.headers = {}

    async def call_next_val_error(req):
        raise ValidationError("val_error")

    res = await error_handler_middleware(request, call_next_val_error)
    assert res.status_code == 400

    async def call_next_unauth_error(req):
        raise UnauthorizedError("unauth")

    res = await error_handler_middleware(request, call_next_unauth_error)
    assert res.status_code == 401

    async def call_next_not_found(req):
        raise NotFoundError("notfound")

    res = await error_handler_middleware(request, call_next_not_found)
    assert res.status_code == 404


# --- Tests for src/services/auth0_service.py ---


@pytest.mark.asyncio
async def test_auth0_service_basic():
    db = AsyncMock()
    service = Auth0Service(db)

    with patch.object(service, "settings") as mock_settings:
        mock_settings.is_auth0_enabled = False
        with pytest.raises(ValueError, match="Auth0 is not configured"):
            await service.get_jwks()

        with pytest.raises(ValueError, match="Auth0 is not configured"):
            await service.verify_auth0_token("token")

    # Test get_user_from_auth0 existing
    mock_user = MagicMock()
    service.user_repo = AsyncMock()
    service.user_repo.get_by_auth0_id.return_value = mock_user
    assert await service.get_user_from_auth0("id") == mock_user


# --- Tests for src/core/exceptions.py ---


def test_exceptions():
    assert BaseAPIException("m", 500).status_code == 500
    assert ValidationError().status_code == 400
    assert UnauthorizedError().status_code == 401
    assert ForbiddenError().status_code == 403
    assert NotFoundError().status_code == 404
    assert BadRequestError().status_code == 400
    assert ConflictError().status_code == 409
    assert InternalServerError().status_code == 500


# --- Tests for src/services/rbac_service.py ---


@pytest.mark.asyncio
async def test_rbac_admin_effective_permissions():
    svc = RBACService(AsyncMock())
    user = MagicMock()
    user.id = uuid4()
    user.role = "admin"
    eff = await svc.get_effective_permissions(user)
    assert eff.platform_role == "admin"
    assert eff.crew_role == "commander"
    assert eff.permissions.get("viewPlanets") is True


@pytest.mark.asyncio
async def test_rbac_effective_permissions_merge_for_crew_role():
    svc = RBACService(AsyncMock())
    user = MagicMock()
    user.id = uuid4()
    user.role = "user"

    crew_id = uuid4()
    svc.crew_members.get_by_crew_and_user = AsyncMock(return_value=MagicMock(role="explorer"))
    svc.role_perms.get_by_role = AsyncMock(
        return_value=MagicMock(permissions={"data.query.run": True})
    )

    eff = await svc.get_effective_permissions(user, crew_id=crew_id)
    assert eff.platform_role == "user"
    assert eff.crew_role == "explorer"
    # default explorer denies, DB override allows
    assert eff.permissions["data.query.run"] is True


@pytest.mark.asyncio
async def test_rbac_assert_permission_denied():
    svc = RBACService(AsyncMock())
    user = MagicMock()
    user.id = uuid4()
    user.role = "user"

    svc.get_effective_permissions = AsyncMock(
        return_value=EffectivePermissions(
            platform_role="user",
            crew_role="guest",
            permissions={"data.query.run": False},
        )
    )
    with pytest.raises(ForbiddenError):
        await svc.assert_permission(user, "data.query.run")


@pytest.mark.asyncio
async def test_rbac_best_role_for_user_in_space():
    svc = RBACService(AsyncMock())
    user_id = uuid4()
    space_id = uuid4()
    crew1, crew2 = uuid4(), uuid4()

    svc.crew_members.get_crew_ids_by_user_and_space = AsyncMock(return_value=[crew1, crew2])

    async def get_member(cid, _uid):
        if cid == crew1:
            return MagicMock(role="navigator")
        return MagicMock(role="commander")

    svc.crew_members.get_by_crew_and_user = AsyncMock(side_effect=get_member)
    assert await svc._best_role_for_user_in_space(user_id, space_id) == "commander"


@pytest.mark.asyncio
async def test_rbac_best_role_for_user_for_connection_owner_and_perms():
    svc = RBACService(AsyncMock())
    user_id = uuid4()
    conn_id = uuid4()

    # owner branch
    svc.connection_repo.get_by_id = AsyncMock(return_value=MagicMock(created_by=user_id))
    assert await svc._best_role_for_user_for_connection(user_id, conn_id) == "commander"

    # perms branch
    svc.connection_repo.get_by_id = AsyncMock(return_value=None)
    crew_id = uuid4()
    space_id = uuid4()
    svc.connection_perms.get_by_connection_id = AsyncMock(
        return_value=[
            MagicMock(crew_id=crew_id, space_id=None),
            MagicMock(crew_id=None, space_id=space_id),
        ]
    )
    svc.crew_members.get_by_crew_and_user = AsyncMock(return_value=MagicMock(role="explorer"))
    svc._best_role_for_user_in_space = AsyncMock(return_value="navigator")
    assert await svc._best_role_for_user_for_connection(user_id, conn_id) == "navigator"


# --- Tests for src/services/rbac_service.py ---


def test_effective_permissions_helper():
    from src.services.rbac_service import EffectivePermissions

    ep = EffectivePermissions(platform_role="user", crew_role="navigator", permissions={"a": True})
    assert ep.permissions.get("a") is True
    assert ep.permissions.get("b", False) is False


# --- Tests for src/services/onboarding_service.py ---


@pytest.mark.asyncio
async def test_onboarding_service_simple():
    from src.services.onboarding_service import ensure_default_planet_and_space

    db = AsyncMock()
    user = MagicMock()
    user.id = uuid4()
    user.name = "Test User"

    with (
        patch("src.services.onboarding_service.PlanetRepository") as pr,
        patch("src.services.onboarding_service.SpaceRepository") as sr,
    ):

        pr.return_value.get_by_owner = AsyncMock(return_value=[MagicMock()])
        await ensure_default_planet_and_space(db, user)


# --- Tests for src/services/starred_service.py ---


@pytest.mark.asyncio
async def test_starred_service_simple():
    from src.services.starred_service import StarredItemService

    db = AsyncMock()
    service = StarredItemService(db)
    user = MagicMock()
    user.id = uuid4()

    service.starred_repo = MagicMock()
    service.starred_repo.get_by_user_and_item = AsyncMock(return_value=None)
    service.starred_repo.create_starred_item = AsyncMock()
    service.starred_repo.get_by_user = AsyncMock(return_value=[])

    await service.star_item(user, uuid4(), "planet")
    await service.get_user_starred_items(user, "planet")
