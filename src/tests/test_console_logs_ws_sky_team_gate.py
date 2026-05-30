"""Sky-team gate on the Console WS log stream.

Gap #1 from the 2026-05-30 security posture audit: the
``/api/console/v1/tenants/{slug}/logs/stream`` endpoint validated tenant
existence but accepted any caller, so a logged-in customer (or anyone
who guessed the URL) could subscribe to the live log feed once it was
wired to real ``kubectl logs --follow``.

These tests are static-analysis level. Exercising the FastAPI WS
TestClient from inside pytest pulls in the full lifespan stack
(Redis, AsyncSession event-loop ownership) and produced unrelated
event-loop / UUID-type flakes in CI without exercising the bit we
care about. The actual policy is short and lives in source, so we
verify the source shape directly. The ``is_sky_team_member`` logic
itself is covered by ``test_console_auth.py``.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from src.api.console_auth import is_sky_team_member
from src.api.v1 import console
from src.core.security import verify_token


_CONSOLE_SOURCE = Path(console.__file__).read_text(encoding="utf-8")


def test_logs_stream_endpoint_exists():
    assert hasattr(console, "stream_tenant_logs"), (
        "stream_tenant_logs route must exist on the Console router"
    )


def test_logs_stream_accepts_token_query_param():
    """The browser WS API cannot set headers, so the JWT comes via the
    ``?token=`` query param. If this signature drifts, the FE will
    silently fall back to an unauthenticated connection."""
    sig = inspect.signature(console.stream_tenant_logs)
    assert "token" in sig.parameters, (
        f"stream_tenant_logs must accept ``token`` for auth; "
        f"signature is {sig}"
    )


def test_logs_stream_source_calls_verify_token():
    """The handler must call ``verify_token`` on the supplied token.
    A refactor that drops this is a silent regression of Gap #1."""
    assert "verify_token(" in _CONSOLE_SOURCE, (
        "stream_tenant_logs must call verify_token() on the supplied JWT"
    )
    assert callable(verify_token)


def test_logs_stream_source_calls_is_sky_team_member():
    """The handler must gate on ``is_sky_team_member``, the same
    predicate ``require_sky_team`` uses. Anything looser grants more on
    the WS surface than on the HTTP surface."""
    assert "is_sky_team_member(" in _CONSOLE_SOURCE, (
        "stream_tenant_logs must call is_sky_team_member() on the resolved user"
    )
    assert callable(is_sky_team_member)


def test_logs_stream_source_closes_with_documented_codes():
    """The FE routes on the close code (4001/4003/4004). If anyone
    rewrites these to 1000/1011/whatever, the FE error-handling layer
    silently degrades."""
    assert re.search(r"close\s*\(\s*code\s*=\s*4001\b", _CONSOLE_SOURCE), (
        "stream_tenant_logs must close with 4001 on unauthenticated"
    )
    assert re.search(r"close\s*\(\s*code\s*=\s*4003\b", _CONSOLE_SOURCE), (
        "stream_tenant_logs must close with 4003 on non-Sky-team"
    )
    assert re.search(r"close\s*\(\s*code\s*=\s*4004\b", _CONSOLE_SOURCE), (
        "stream_tenant_logs must close with 4004 on missing tenant"
    )
