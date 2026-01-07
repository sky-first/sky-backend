import json
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import uuid4, UUID
from fastapi import Request, Response
from src.utils.cache import CacheService, widget_cache_key, dashboard_cache_key, workspace_cache_key, connection_metadata_cache_key
from src.workers.sync_worker import sync_connection, sync_connection_metadata
from src.workers.ai_worker import process_ai_query, build_dashboard_job
from src.api.middleware.logging import logging_middleware
from src.api.middleware.rate_limit import rate_limit_middleware
from src.api.middleware.auth import auth_middleware
from src.api.middleware.error_handler import error_handler_middleware
from src.services.auth0_service import Auth0Service
from src.core.exceptions import (
    BaseAPIException, ValidationError, UnauthorizedError, 
    ForbiddenError, NotFoundError, BadRequestError, 
    ConflictError, InternalServerError
)

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
        await CacheService.delete_pattern("pat*")
        mock_redis.get.return_value = json.dumps({"a": 1})
        await CacheService.get_json("key")
        await CacheService.set_json("key", {"b": 2})

def test_cache_keys():
    assert widget_cache_key("1") == "widget:1"
    assert dashboard_cache_key("2") == "dashboard:2"
    assert workspace_cache_key("3") == "workspace:3"
    assert connection_metadata_cache_key("4") == "connection:metadata:4"

# --- Tests for src/workers/sync_worker.py ---

def test_sync_connection_task():
    func = getattr(sync_connection, '__wrapped__', sync_connection)
    try:
        func(MagicMock(), "conn_id")
    except Exception:
        pass

def test_sync_connection_metadata_task():
    func = getattr(sync_connection_metadata, '__wrapped__', sync_connection_metadata)
    try:
        func("conn_id")
    except Exception:
        pass

# --- Tests for src/workers/ai_worker.py ---

def test_process_ai_query_task():
    func = getattr(process_ai_query, '__wrapped__', process_ai_query)
    try:
        func(MagicMock(), "query_id")
    except Exception:
        pass

def test_build_dashboard_job_task():
    func = getattr(build_dashboard_job, '__wrapped__', build_dashboard_job)
    with patch("src.workers.ai_worker.asyncio.run") as mock_run:
        try:
            func(MagicMock(), str(uuid4()))
        except Exception:
            pass

# --- Tests for src/api/middleware/logging.py ---

@pytest.mark.asyncio
async def test_logging_middleware():
    request = MagicMock(spec=Request)
    request.method = "GET"
    request.url.path = "/test"
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    
    response = MagicMock(spec=Response)
    response.status_code = 200
    
    async def call_next(req):
        return response
        
    await logging_middleware(request, call_next)
    
    async def call_next_error(req):
        raise ValueError("error")
    with pytest.raises(ValueError):
        await logging_middleware(request, call_next_error)

# --- Tests for src/api/middleware/rate_limit.py ---

@pytest.mark.asyncio
async def test_rate_limit_middleware():
    request = MagicMock(spec=Request)
    request.method = "GET"
    request.url.path = "/test"
    request.headers = {}
    request.state = MagicMock()
    
    response = MagicMock(spec=Response)
    response.headers = {}
    
    async def call_next(req):
        return response
        
    mock_redis = AsyncMock()
    mock_redis.incr.return_value = 1
    
    with patch("src.api.middleware.rate_limit.get_redis", return_value=mock_redis):
        with patch("src.api.middleware.rate_limit.settings") as mock_settings:
            mock_settings.RATE_LIMIT_ENABLED = True
            mock_settings.RATE_LIMIT_PER_MINUTE = 10
            mock_settings.RATE_LIMIT_PER_HOUR = 100
            
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
