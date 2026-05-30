"""Tests for the provisioning router (webhook + SSE)."""

from __future__ import annotations

import json
import uuid
from typing import AsyncIterator

import pytest

from src.api.console_auth import require_sky_team
from src.api.deps import get_current_user
from src.main import app
from src.models.internal_console import (
    PROVISIONING_PHASES,
    ProvisioningJob,
    ProvisioningJobEventStatus,
    ProvisioningJobStatus,
    ProvisioningJobType,
)
from src.models.user import User
from src.services import provisioning_workflow as pw


# ── Fixtures ───────────────────────────────────────────────────────


WEBHOOK_SECRET = "test-shared-secret"


@pytest.fixture(autouse=True)
def _configure_secret_and_redis(monkeypatch):
    monkeypatch.setenv(pw.PROVISIONING_WEBHOOK_SECRET_ENV, WEBHOOK_SECRET)

    async def _no_redis():
        return None

    import src.config.redis as redis_cfg

    monkeypatch.setattr(redis_cfg, "get_redis", _no_redis)
    yield


@pytest.fixture
def sky_team_user():
    return User(
        id=uuid.uuid4(),
        email="lucas@skyfirstlabs.com",
        password_hash="",
        name="Lucas",
        role="admin",
        email_verified=True,
        has_completed_onboarding=True,
        is_sky_operator=True,
    )


@pytest.fixture
def authed_client(client, sky_team_user):
    app.dependency_overrides[get_current_user] = lambda: sky_team_user
    app.dependency_overrides[require_sky_team] = lambda: sky_team_user
    yield client
    app.dependency_overrides.pop(require_sky_team, None)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
async def existing_job(db_session) -> ProvisioningJob:
    job = ProvisioningJob(
        id=uuid.uuid4(),
        tenant_slug="acme",
        actor_email="lucas@skyfirstlabs.com",
        job_type=ProvisioningJobType.CREATE.value,
        status=ProvisioningJobStatus.PENDING.value,
        request_payload={"tier": "starter"},
    )
    db_session.add(job)
    await db_session.commit()
    return job


# ── Webhook ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_valid_signature_accepts_event(authed_client, existing_job):
    body = {
        "job_id": str(existing_job.id),
        "phase": "preflight",
        "status": ProvisioningJobEventStatus.STARTED.value,
        "level": "info",
        "message": "starting preflight",
        "metadata": {"runner": "ubuntu-22.04"},
    }
    body_bytes = json.dumps(body).encode("utf-8")
    sig = pw.compute_signature(WEBHOOK_SECRET, body_bytes)

    res = authed_client.post(
        "/api/console/v1/jobs/webhook",
        data=body_bytes,
        headers={
            "Content-Type": "application/json",
            pw.WEBHOOK_SIGNATURE_HEADER: sig,
        },
    )
    assert res.status_code == 202, res.text
    out = res.json()
    assert out["accepted"] is True
    assert out["id"]


@pytest.mark.asyncio
async def test_webhook_invalid_signature_returns_401(authed_client, existing_job):
    body_bytes = json.dumps(
        {
            "job_id": str(existing_job.id),
            "phase": "preflight",
            "status": "started",
        }
    ).encode("utf-8")
    res = authed_client.post(
        "/api/console/v1/jobs/webhook",
        data=body_bytes,
        headers={
            "Content-Type": "application/json",
            pw.WEBHOOK_SIGNATURE_HEADER: "deadbeef" * 8,
        },
    )
    assert res.status_code == 401
    body = res.json()
    # Error middleware wraps HTTPException as {"error": {"message": ...}};
    # tolerate both shapes so the test isn't coupled to the wrapper.
    msg = body.get("detail") or body.get("error", {}).get("message")
    assert msg == "invalid signature"


@pytest.mark.asyncio
async def test_webhook_missing_signature_returns_401(authed_client, existing_job):
    body_bytes = json.dumps(
        {
            "job_id": str(existing_job.id),
            "phase": "preflight",
            "status": "started",
        }
    ).encode("utf-8")
    res = authed_client.post(
        "/api/console/v1/jobs/webhook",
        data=body_bytes,
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_webhook_unknown_job_returns_404(authed_client):
    body = {
        "job_id": str(uuid.uuid4()),
        "phase": "preflight",
        "status": "started",
    }
    body_bytes = json.dumps(body).encode("utf-8")
    sig = pw.compute_signature(WEBHOOK_SECRET, body_bytes)
    res = authed_client.post(
        "/api/console/v1/jobs/webhook",
        data=body_bytes,
        headers={
            "Content-Type": "application/json",
            pw.WEBHOOK_SIGNATURE_HEADER: sig,
        },
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_webhook_missing_required_field_returns_422(authed_client):
    body = {"job_id": str(uuid.uuid4())}  # no phase / status
    body_bytes = json.dumps(body).encode("utf-8")
    sig = pw.compute_signature(WEBHOOK_SECRET, body_bytes)
    res = authed_client.post(
        "/api/console/v1/jobs/webhook",
        data=body_bytes,
        headers={
            "Content-Type": "application/json",
            pw.WEBHOOK_SIGNATURE_HEADER: sig,
        },
    )
    assert res.status_code == 422


# ── SSE ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_events_stream_replays_history(authed_client, existing_job, db_session):
    # Seed two events directly through the service, then GET /events.
    for phase in ("preflight", "plan"):
        await pw.ingest_event(
            db_session,
            pw.WebhookPayload(
                job_id=str(existing_job.id),
                phase=phase,
                status=ProvisioningJobEventStatus.SUCCEEDED.value,
            ),
        )
    await db_session.commit()

    # The SSE endpoint streams indefinitely; read a chunk and break out
    # to confirm the replay frames are emitted before the live tail.
    with authed_client.stream(
        "GET", f"/api/console/v1/jobs/{existing_job.id}/events"
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        collected = b""
        for chunk in resp.iter_bytes():
            collected += chunk
            # Once we've seen both replay events we're done.
            text = collected.decode("utf-8", errors="ignore")
            if text.count('"phase": "preflight"') >= 1 and text.count(
                '"phase": "plan"'
            ) >= 1:
                break
            if len(collected) > 65536:
                break  # safety net
    text = collected.decode("utf-8", errors="ignore")
    assert '"phase": "preflight"' in text
    assert '"phase": "plan"' in text


@pytest.mark.asyncio
async def test_events_stream_unknown_job_returns_404(authed_client):
    res = authed_client.get(f"/api/console/v1/jobs/{uuid.uuid4()}/events")
    assert res.status_code == 404
