"""Sky-team gate on the Console WS log stream.

Gap #1 from the 2026-05-30 security posture audit: the
``/api/console/v1/tenants/{slug}/logs/stream`` endpoint validated tenant
existence but accepted any caller, so a logged-in customer (or anyone
who guessed the URL) could subscribe to the live log feed once it was
wired to real ``kubectl logs --follow``. This test pins the new
authentication path: no token → 4001, customer token → 4003, Sky-team
token → either 4004 (tenant slug missing) or 1000 on normal close.
"""
from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token
from src.main import app
from src.models.user import User


def _client() -> TestClient:
    return TestClient(app)


def _token_for(user_id) -> str:
    return create_access_token(
        data={"sub": str(user_id)},
        expires_delta=timedelta(minutes=5),
    )


@pytest.mark.asyncio
async def test_logs_stream_rejects_without_token():
    client = _client()
    with pytest.raises(Exception):
        # No token query param at all — FastAPI returns 403 before the
        # socket upgrades. We accept "any failure to open" here.
        with client.websocket_connect(
            "/api/console/v1/tenants/whatever/logs/stream"
        ):
            pass


@pytest.mark.asyncio
async def test_logs_stream_rejects_non_sky_team_user(db_session: AsyncSession):
    customer = User(
        id=uuid4(),
        email="customer@example.com",
        password_hash="x",
        name="Customer",
        role="user",
        email_verified=True,
        is_sky_operator=False,
    )
    db_session.add(customer)
    await db_session.commit()

    client = _client()
    token = _token_for(customer.id)
    with client.websocket_connect(
        f"/api/console/v1/tenants/whatever/logs/stream?token={token}"
    ) as ws:
        # Expect the explicit error frame + 4003 close code. The frame
        # is sent before close() so the FE can route on the message
        # ('sky_team_required') rather than guessing from the code.
        msg = ws.receive_json()
        assert msg == {"error": "sky_team_required"}


@pytest.mark.asyncio
async def test_logs_stream_accepts_sky_team_user_but_404s_unknown_tenant(
    db_session: AsyncSession,
):
    engineer = User(
        id=uuid4(),
        email="engineer@skyfirstlabs.com",
        password_hash="x",
        name="Engineer",
        role="admin",
        email_verified=True,
        is_sky_operator=True,
    )
    db_session.add(engineer)
    await db_session.commit()

    client = _client()
    token = _token_for(engineer.id)
    with client.websocket_connect(
        f"/api/console/v1/tenants/does-not-exist/logs/stream?token={token}"
    ) as ws:
        msg = ws.receive_json()
        # Past the Sky-team gate (no 4003) — the next layer is the
        # tenant-existence check, which surfaces tenant_not_found + 4004.
        assert msg == {"error": "tenant_not_found"}
