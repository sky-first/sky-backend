from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.responses import JSONResponse
from jose import JWTError

from src.core.exceptions import (
    BadRequestError,
    BaseAPIException,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)


@pytest.mark.asyncio
async def test_error_handler_middleware_success(monkeypatch):
    from src.api.middleware.error_handler import error_handler_middleware

    request = MagicMock()

    resp = JSONResponse(status_code=200, content={"ok": True})

    async def call_next(_req):
        return resp

    out = await error_handler_middleware(request, call_next)
    assert out.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc, expected_status, expected_error",
    [
        (ValidationError("v"), 400, "Validation Error"),
        (UnauthorizedError("u"), 401, "Unauthorized"),
        (ForbiddenError("f"), 403, "Forbidden"),
        (NotFoundError("n"), 404, "Not Found"),
        (BadRequestError("b"), 400, "Bad Request"),
        (ConflictError("c"), 409, "Conflict"),
    ],
)
async def test_error_handler_middleware_known_exceptions(
    monkeypatch, exc, expected_status, expected_error
):
    from src.api.middleware import error_handler as eh
    from src.config.settings import settings as app_settings

    # Ensure CORS header is reflected
    app_settings.CORS_ORIGINS = "http://localhost:3000"

    request = MagicMock()
    request.headers = {"Origin": "http://localhost:3000"}

    async def call_next(_req):
        raise exc

    out = await eh.error_handler_middleware(request, call_next)
    assert out.status_code == expected_status
    payload = out.body.decode()
    assert expected_error in payload
    assert out.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"


@pytest.mark.asyncio
async def test_error_handler_middleware_jwt_error(monkeypatch):
    from src.api.middleware import error_handler as eh

    request = MagicMock()
    request.headers = {}

    async def call_next(_req):
        raise JWTError("bad token")

    out = await eh.error_handler_middleware(request, call_next)
    assert out.status_code == 401


@pytest.mark.asyncio
async def test_error_handler_middleware_base_api_exception(monkeypatch):
    from src.api.middleware import error_handler as eh

    request = MagicMock()
    request.headers = {}

    class CustomAPIError(BaseAPIException):
        pass

    async def call_next(_req):
        raise CustomAPIError("boom", status_code=418)

    out = await eh.error_handler_middleware(request, call_next)
    assert out.status_code == 418
    assert b"API Error" in out.body


@pytest.mark.asyncio
async def test_error_handler_middleware_unhandled_exception_debug_toggle(monkeypatch):
    from src.api.middleware import error_handler as eh
    from src.config.settings import settings as app_settings

    request = MagicMock()
    request.headers = {}

    async def call_next(_req):
        raise RuntimeError("kaboom")

    # DEBUG False => generic message
    app_settings.DEBUG = False
    out = await eh.error_handler_middleware(request, call_next)
    assert out.status_code == 500
    assert b"An unexpected error occurred" in out.body

    # DEBUG True => includes message + details
    app_settings.DEBUG = True
    out = await eh.error_handler_middleware(request, call_next)
    assert out.status_code == 500
    assert b"kaboom" in out.body


@pytest.mark.asyncio
async def test_error_handler_middleware_exception_group_if_available(monkeypatch):
    from src.api.middleware import error_handler as eh

    # ExceptionGroup only exists on Python 3.11+. On 3.9 this test is a no-op.
    EG = getattr(__builtins__, "ExceptionGroup", None)
    if EG is None:
        pytest.skip("ExceptionGroup not available on this Python")

    request = MagicMock()
    request.headers = {}

    async def call_next(_req):
        raise EG("group", [UnauthorizedError("nope")])

    out = await eh.error_handler_middleware(request, call_next)
    assert out.status_code == 401


@pytest.mark.asyncio
async def test_postgresql_connector(monkeypatch):
    import src.connectors.postgresql as pg_mod
    from src.connectors.postgresql import PostgreSQLConnector

    connector = PostgreSQLConnector()
    cfg = {"host": "h", "username": "u", "password": "p", "database": "d", "port": 5432}

    conn = SimpleNamespace(
        close=AsyncMock(),
        fetch=AsyncMock(return_value=[{"a": 1}, {"b": 2}]),
    )

    # success test_connection
    class AsyncContextManagerMock:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, exc_type, exc, tb):
            await conn.close()

    monkeypatch.setattr(pg_mod.asyncpg, "connect", lambda **_kwargs: AsyncContextManagerMock())
    assert await connector.test_connection(cfg) is True
    conn.close.assert_awaited()

    # failure test_connection
    class FailContextManagerMock:
        async def __aenter__(self):
            raise RuntimeError("no")

        async def __aexit__(self, exc_type, exc, tb):
            pass

    monkeypatch.setattr(pg_mod.asyncpg, "connect", lambda **_kwargs: FailContextManagerMock())
    assert await connector.test_connection(cfg) is False

    # execute_query closes conn in finally
    monkeypatch.setattr(pg_mod.asyncpg, "connect", lambda **_kwargs: AsyncContextManagerMock())
    rows = await connector.execute_query(cfg, "select 1")
    assert rows == [{"a": 1}, {"b": 2}]
    assert conn.close.await_count >= 2


@pytest.mark.asyncio
async def test_mysql_connector():
    from src.connectors.mysql import MySQLConnector

    c = MySQLConnector()
    assert await c.test_connection({}) is False
    assert await c.get_metadata({}) == {"tables": [], "schemas": []}
    assert await c.execute_query({}, "select 1") == []
    assert await c.sync_data({}) == {"status": "success"}


def test_connector_registry():
    from src.connectors.registry import get_connector

    assert get_connector("postgresql") is not None
    assert get_connector("mysql") is not None
    with pytest.raises(ValueError):
        get_connector("does-not-exist")
