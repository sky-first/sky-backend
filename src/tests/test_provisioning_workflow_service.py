"""Unit tests for ``src.services.provisioning_workflow``.

The webhook signing helpers are pure; the lifecycle helpers
(``ingest_event``, ``replay_events``) talk to the DB through the
shared ``db_session`` fixture, which spins up SQLite in-memory. No
real Redis required — ``_publish`` swallows ``RuntimeError`` from
the test's stub ``get_redis``.
"""

from __future__ import annotations

import uuid
from typing import Optional

import pytest
from sqlalchemy import select

from src.models.internal_console import (
    PROVISIONING_PHASES,
    ProvisioningJob,
    ProvisioningJobEvent,
    ProvisioningJobEventLevel,
    ProvisioningJobEventStatus,
    ProvisioningJobStatus,
    ProvisioningJobType,
)
from src.services import provisioning_workflow as pw


# ── Signature helpers ─────────────────────────────────────────────


def test_compute_signature_is_deterministic_hex():
    sig = pw.compute_signature("topsecret", b'{"a":1}')
    assert isinstance(sig, str)
    assert len(sig) == 64
    int(sig, 16)  # parses as hex
    # Same inputs → same digest.
    assert sig == pw.compute_signature("topsecret", b'{"a":1}')


def test_signature_roundtrip_verifies():
    secret = "shared-secret"
    body = b'{"phase":"preflight","status":"started"}'
    sig = pw.compute_signature(secret, body)
    assert pw.verify_signature(secret, body, sig) is True


def test_signature_rejects_wrong_secret():
    body = b"{}"
    sig = pw.compute_signature("a", body)
    assert pw.verify_signature("b", body, sig) is False


def test_signature_rejects_tampered_body():
    secret = "k"
    sig = pw.compute_signature(secret, b'{"x":1}')
    assert pw.verify_signature(secret, b'{"x":2}', sig) is False


def test_signature_rejects_empty_secret():
    """Empty secret always returns False — fail-closed."""
    assert pw.verify_signature("", b"x", "anything") is False
    assert pw.verify_signature(None, b"x", "anything") is False  # type: ignore[arg-type]


def test_signature_rejects_empty_signature():
    assert pw.verify_signature("k", b"x", "") is False


# ── ingest_event lifecycle ────────────────────────────────────────


async def _make_job(db_session, slug: str = "acme") -> ProvisioningJob:
    job = ProvisioningJob(
        id=uuid.uuid4(),
        tenant_slug=slug,
        actor_email="lucas@skyfirstlabs.com",
        job_type=ProvisioningJobType.CREATE.value,
        status=ProvisioningJobStatus.PENDING.value,
        request_payload={"tier": "starter"},
    )
    db_session.add(job)
    await db_session.commit()
    return job


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    """Stub out ``get_redis`` so publish is a silent no-op in tests."""

    async def _gone():
        return None

    # Provide a fake config.redis module attr so the lazy import inside
    # ``_publish`` resolves to our stub.
    import src.config.redis as redis_cfg

    monkeypatch.setattr(redis_cfg, "get_redis", _gone)
    yield


@pytest.mark.asyncio
async def test_ingest_event_appends_and_promotes_pending_to_running(db_session):
    job = await _make_job(db_session)
    payload = pw.WebhookPayload(
        job_id=str(job.id),
        phase="preflight",
        status=ProvisioningJobEventStatus.STARTED.value,
    )
    event = await pw.ingest_event(db_session, payload)
    await db_session.commit()

    assert event.id is not None
    assert event.phase == "preflight"
    refreshed = (
        await db_session.execute(
            select(ProvisioningJob).where(ProvisioningJob.id == job.id)
        )
    ).scalar_one()
    # Started event flips pending → running but does NOT advance phase.
    assert refreshed.status == ProvisioningJobStatus.RUNNING.value
    assert refreshed.current_phase is None


@pytest.mark.asyncio
async def test_ingest_event_succeeded_advances_current_phase(db_session):
    job = await _make_job(db_session)

    # preflight succeeded → current_phase = preflight
    await pw.ingest_event(
        db_session,
        pw.WebhookPayload(
            job_id=str(job.id),
            phase="preflight",
            status=ProvisioningJobEventStatus.SUCCEEDED.value,
        ),
    )
    # plan succeeded → current_phase = plan
    await pw.ingest_event(
        db_session,
        pw.WebhookPayload(
            job_id=str(job.id),
            phase="plan",
            status=ProvisioningJobEventStatus.SUCCEEDED.value,
        ),
    )
    await db_session.commit()

    refreshed = (
        await db_session.execute(
            select(ProvisioningJob).where(ProvisioningJob.id == job.id)
        )
    ).scalar_one()
    assert refreshed.current_phase == "plan"
    assert refreshed.status == ProvisioningJobStatus.RUNNING.value


@pytest.mark.asyncio
async def test_ingest_event_terminal_phase_marks_success(db_session):
    job = await _make_job(db_session)
    await pw.ingest_event(
        db_session,
        pw.WebhookPayload(
            job_id=str(job.id),
            phase=PROVISIONING_PHASES[-1],  # "report"
            status=ProvisioningJobEventStatus.SUCCEEDED.value,
        ),
    )
    await db_session.commit()

    refreshed = (
        await db_session.execute(
            select(ProvisioningJob).where(ProvisioningJob.id == job.id)
        )
    ).scalar_one()
    assert refreshed.status == ProvisioningJobStatus.SUCCESS.value
    assert refreshed.current_phase == "report"
    assert refreshed.completed_at is not None


@pytest.mark.asyncio
async def test_ingest_event_failed_marks_job_failed(db_session):
    job = await _make_job(db_session)
    await pw.ingest_event(
        db_session,
        pw.WebhookPayload(
            job_id=str(job.id),
            phase="gitops",
            status=ProvisioningJobEventStatus.FAILED.value,
            level=ProvisioningJobEventLevel.ERROR.value,
            message="kubectl apply returned 1",
        ),
    )
    await db_session.commit()

    refreshed = (
        await db_session.execute(
            select(ProvisioningJob).where(ProvisioningJob.id == job.id)
        )
    ).scalar_one()
    assert refreshed.status == ProvisioningJobStatus.FAILED.value
    assert refreshed.completed_at is not None
    assert refreshed.error_message == "kubectl apply returned 1"


@pytest.mark.asyncio
async def test_ingest_event_does_not_rollback_phase(db_session):
    """A late ``succeeded`` for an earlier phase must not move the pointer back."""
    job = await _make_job(db_session)
    await pw.ingest_event(
        db_session,
        pw.WebhookPayload(
            job_id=str(job.id),
            phase="gitops",
            status=ProvisioningJobEventStatus.SUCCEEDED.value,
        ),
    )
    await pw.ingest_event(
        db_session,
        pw.WebhookPayload(
            job_id=str(job.id),
            phase="preflight",
            status=ProvisioningJobEventStatus.SUCCEEDED.value,
        ),
    )
    await db_session.commit()

    refreshed = (
        await db_session.execute(
            select(ProvisioningJob).where(ProvisioningJob.id == job.id)
        )
    ).scalar_one()
    assert refreshed.current_phase == "gitops"


@pytest.mark.asyncio
async def test_ingest_event_unknown_job_raises_value_error(db_session):
    with pytest.raises(ValueError):
        await pw.ingest_event(
            db_session,
            pw.WebhookPayload(
                job_id=str(uuid.uuid4()),
                phase="preflight",
                status=ProvisioningJobEventStatus.STARTED.value,
            ),
        )


# ── replay_events ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_replay_events_returns_chronological_order(db_session):
    job = await _make_job(db_session)
    for phase in ("preflight", "plan", "gitops"):
        await pw.ingest_event(
            db_session,
            pw.WebhookPayload(
                job_id=str(job.id),
                phase=phase,
                status=ProvisioningJobEventStatus.SUCCEEDED.value,
            ),
        )
    await db_session.commit()

    events = await pw.replay_events(db_session, job.id)
    assert [e.phase for e in events] == ["preflight", "plan", "gitops"]


@pytest.mark.asyncio
async def test_replay_events_empty_for_unknown_job(db_session):
    events = await pw.replay_events(db_session, uuid.uuid4())
    assert events == []
