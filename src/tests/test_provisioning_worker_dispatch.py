"""Unit tests for ``src.workers.provisioning_worker``.

We don't import the live Celery task body (Celery harness brings up a
broker connection); we exercise the async core ``_provision_async``
directly with the HTTP layer mocked via ``respx``-style monkeypatch
of ``httpx.AsyncClient``.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from src.models.internal_console import (
    ProvisioningJob,
    ProvisioningJobStatus,
    ProvisioningJobType,
)
from src.workers import provisioning_worker as pwk


@pytest.fixture(autouse=True)
def _gh_env(monkeypatch):
    monkeypatch.setenv(pwk.GH_TOKEN_ENV, "ghp_testtoken")
    monkeypatch.setenv(pwk.GH_OWNER_ENV, "sky-first")
    monkeypatch.setenv(pwk.GH_REPO_ENV, "sky-poc-infra")
    monkeypatch.setenv(pwk.GH_WORKFLOW_ENV, "onboard-client.yml")
    monkeypatch.setenv(pwk.GH_REF_ENV, "main")
    monkeypatch.setenv(pwk.WEBHOOK_URL_ENV, "https://api.sky.test/api/console/v1/jobs/webhook")
    monkeypatch.setenv(pwk.WEBHOOK_SECRET_ENV, "shared-secret")
    yield


async def _seed_job(db_session) -> ProvisioningJob:
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


class _FakeResponse:
    def __init__(self, status_code: int, body: Optional[dict] = None):
        self.status_code = status_code
        self._body = body or {}
        self.text = json.dumps(self._body)

    def json(self) -> Any:
        return self._body


class _FakeAsyncClient:
    """Drop-in for ``httpx.AsyncClient`` covering only the two calls we make."""

    def __init__(self, dispatch_status: int = 204, runs_payload: Optional[dict] = None):
        self.dispatch_status = dispatch_status
        self.runs_payload = runs_payload or {
            "workflow_runs": [
                {
                    "id": 9876543210,
                    "html_url": "https://github.com/sky-first/sky-poc-infra/actions/runs/9876543210",
                    "name": "onboard-client",
                }
            ]
        }
        self.posted: list[tuple[str, dict]] = []
        self.got: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, headers=None):
        self.posted.append((url, json))
        return _FakeResponse(self.dispatch_status)

    async def get(self, url, headers=None):
        self.got.append(url)
        return _FakeResponse(200, self.runs_payload)


@pytest.mark.asyncio
async def test_provision_async_dispatches_and_stores_run_url(db_session, monkeypatch):
    job = await _seed_job(db_session)
    fake = _FakeAsyncClient()

    # Patch the AsyncSessionLocal used by the worker to yield our test
    # session, and the HTTP client to return our fake.
    class _SessionCM:
        async def __aenter__(self_inner):
            return db_session

        async def __aexit__(self_inner, exc_type, exc, tb):
            return False

    monkeypatch.setattr(pwk, "AsyncSessionLocal", lambda: _SessionCM())
    monkeypatch.setattr(pwk.httpx, "AsyncClient", lambda **kw: fake)
    # Speed up the lookup loop.
    monkeypatch.setattr(pwk, "RUN_LOOKUP_SLEEP_SECONDS", 0)

    result = await pwk._provision_async(str(job.id))

    assert result["ok"] is True
    assert result["external_run_id"] == "9876543210"
    assert "9876543210" in result["external_run_url"]
    # The POST hit the workflow_dispatch endpoint with our inputs.
    assert any("/actions/workflows/onboard-client.yml/dispatches" in u for u, _ in fake.posted)
    url, body = fake.posted[0]
    assert body["ref"] == "main"
    inputs = body["inputs"]
    assert inputs["job_id"] == str(job.id)
    assert inputs["tenant_slug"] == "acme"
    assert inputs["webhook_secret"] == "shared-secret"
    assert "dispatch_token" in inputs

    # Persisted on the job row.
    refreshed = (
        await db_session.execute(
            select(ProvisioningJob).where(ProvisioningJob.id == job.id)
        )
    ).scalar_one()
    assert refreshed.external_run_id == "9876543210"
    assert refreshed.external_run_url.endswith("/runs/9876543210")
    assert refreshed.status == ProvisioningJobStatus.RUNNING.value


@pytest.mark.asyncio
async def test_provision_async_missing_token_marks_failed(db_session, monkeypatch):
    monkeypatch.delenv(pwk.GH_TOKEN_ENV, raising=False)
    job = await _seed_job(db_session)

    class _SessionCM:
        async def __aenter__(self_inner):
            return db_session

        async def __aexit__(self_inner, exc_type, exc, tb):
            return False

    monkeypatch.setattr(pwk, "AsyncSessionLocal", lambda: _SessionCM())

    result = await pwk._provision_async(str(job.id))
    assert result["ok"] is False
    assert result["reason"] == "missing_token"

    refreshed = (
        await db_session.execute(
            select(ProvisioningJob).where(ProvisioningJob.id == job.id)
        )
    ).scalar_one()
    assert refreshed.status == ProvisioningJobStatus.FAILED.value
    assert pwk.GH_TOKEN_ENV in (refreshed.error_message or "")


@pytest.mark.asyncio
async def test_provision_async_gh_dispatch_failure_marks_failed(db_session, monkeypatch):
    job = await _seed_job(db_session)

    class _SessionCM:
        async def __aenter__(self_inner):
            return db_session

        async def __aexit__(self_inner, exc_type, exc, tb):
            return False

    monkeypatch.setattr(pwk, "AsyncSessionLocal", lambda: _SessionCM())
    fake = _FakeAsyncClient(dispatch_status=403)
    monkeypatch.setattr(pwk.httpx, "AsyncClient", lambda **kw: fake)
    monkeypatch.setattr(pwk, "RUN_LOOKUP_SLEEP_SECONDS", 0)

    result = await pwk._provision_async(str(job.id))
    assert result["ok"] is False
    assert result["reason"] == "dispatch_error"

    refreshed = (
        await db_session.execute(
            select(ProvisioningJob).where(ProvisioningJob.id == job.id)
        )
    ).scalar_one()
    assert refreshed.status == ProvisioningJobStatus.FAILED.value
    assert "403" in (refreshed.error_message or "")


@pytest.mark.asyncio
async def test_provision_async_unknown_job_returns_not_found(db_session, monkeypatch):
    class _SessionCM:
        async def __aenter__(self_inner):
            return db_session

        async def __aexit__(self_inner, exc_type, exc, tb):
            return False

    monkeypatch.setattr(pwk, "AsyncSessionLocal", lambda: _SessionCM())
    result = await pwk._provision_async(str(uuid.uuid4()))
    assert result == {
        "ok": False,
        "reason": "job_not_found",
        "job_id": result["job_id"],
    }
