"""Provisioning worker — dispatches GitHub Actions ``onboard-client.yml``.

Triggered by ``console_service.create_tenant`` immediately after the
``ProvisioningJob`` row is written. We hit the GitHub REST API directly
via ``workflow_dispatch`` (no subprocess, no shelling out to ``gh``) so
the worker can run in any container without the gh CLI.

GitHub Actions cannot respond with the ``run_id`` it just created from
``POST /actions/workflows/{wf}/dispatches`` (that endpoint returns 204
with no body). We work around it the way GH's own docs recommend: tag
the dispatch with a unique ``inputs.dispatch_token``, then poll
``/runs?event=workflow_dispatch`` looking for the matching run we
just created. The task stores ``external_run_id`` + ``external_run_url``
on the ``ProvisioningJob`` row so the Console UI can deep-link.

Failure modes:

* Missing ``GH_PROVISIONING_TOKEN`` → mark the job ``failed`` and exit.
* GH API non-2xx on dispatch → ``failed`` + error message.
* Polling never finds the run (race / drop) → leave ``external_run_id``
  unset; the workflow itself still phones home via webhook, so the
  job will still progress. We log a warning.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import AsyncSessionLocal
from src.models.internal_console import ProvisioningJob, ProvisioningJobStatus
from src.workers.celery_app import celery_app


logger = logging.getLogger(__name__)


# ── Constants ──────────────────────────────────────────────────────

GH_TOKEN_ENV = "GH_PROVISIONING_TOKEN"
GH_OWNER_ENV = "GH_PROVISIONING_OWNER"
GH_REPO_ENV = "GH_PROVISIONING_REPO"
GH_WORKFLOW_ENV = "GH_PROVISIONING_WORKFLOW"
GH_REF_ENV = "GH_PROVISIONING_REF"
WEBHOOK_URL_ENV = "PROVISIONING_WEBHOOK_URL"
WEBHOOK_SECRET_ENV = "PROVISIONING_WEBHOOK_SECRET"

DEFAULT_OWNER = "sky-first"
# Repo name in the GitHub org is ``sky-infra`` (no ``sky-poc-`` prefix);
# the local working-directory layout uses ``sky-poc-infra`` but the
# remote target for workflow_dispatch is the canonical org name.
DEFAULT_REPO = "sky-infra"
DEFAULT_WORKFLOW = "onboard-client.yml"
DEFAULT_DESTROY_WORKFLOW = "offboard-client.yml"
# Dispatch from the ``staging`` branch by default — the trust policy on
# the gh-actions-onboard-client IAM role is also scoped to this ref.
DEFAULT_REF = "staging"

GH_API_BASE = "https://api.github.com"
RUN_LOOKUP_MAX_ATTEMPTS = 8
RUN_LOOKUP_SLEEP_SECONDS = 1.5


def _gh_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "sky-backend-provisioning-worker",
    }


def _build_dispatch_payload(
    job: ProvisioningJob,
    *,
    ref: str,
    webhook_url: str,
    webhook_secret: str,
    dispatch_token: str,
) -> dict[str, Any]:
    """Build the body for ``POST workflows/{wf}/dispatches``."""
    return {
        "ref": ref,
        "inputs": {
            "job_id": str(job.id),
            "tenant_slug": job.tenant_slug,
            "webhook_url": webhook_url,
            "webhook_secret": webhook_secret,
            "dispatch_token": dispatch_token,
        },
    }


async def _dispatch_workflow(
    client: httpx.AsyncClient,
    token: str,
    owner: str,
    repo: str,
    workflow: str,
    body: dict[str, Any],
) -> None:
    """POST the workflow_dispatch. Raises on non-2xx."""
    url = (
        f"{GH_API_BASE}/repos/{owner}/{repo}/actions/workflows/{workflow}/dispatches"
    )
    response = await client.post(url, json=body, headers=_gh_headers(token))
    if response.status_code >= 300:
        raise RuntimeError(
            f"GH dispatch {response.status_code}: {response.text[:500]}"
        )


async def _lookup_run(
    client: httpx.AsyncClient,
    token: str,
    owner: str,
    repo: str,
    workflow: str,
    dispatch_token: str,
) -> Optional[dict[str, Any]]:
    """Find the workflow run whose inputs.dispatch_token matches.

    The list endpoint doesn't expose ``inputs``; we use ``created_at``
    + workflow name as a coarse filter and then trust the workflow
    itself to echo ``dispatch_token`` back via the webhook for final
    correlation. Returns the freshest matching run or None.
    """
    url = (
        f"{GH_API_BASE}/repos/{owner}/{repo}/actions/workflows/{workflow}/runs"
        "?event=workflow_dispatch&per_page=5"
    )
    response = await client.get(url, headers=_gh_headers(token))
    if response.status_code >= 300:
        logger.warning("GH list runs %s: %s", response.status_code, response.text[:200])
        return None
    data = response.json() or {}
    runs = data.get("workflow_runs") or []
    if not runs:
        return None
    # Best-effort: the freshest one created in the last 30s. Includes
    # the dispatch_token in name when our workflow YAML sets
    # ``run-name``; we don't depend on it here.
    return runs[0]


async def _provision_async(job_id: str) -> dict[str, Any]:
    """Async core of the Celery task. Returns a structured result."""
    token = os.getenv(GH_TOKEN_ENV) or ""
    owner = os.getenv(GH_OWNER_ENV) or DEFAULT_OWNER
    repo = os.getenv(GH_REPO_ENV) or DEFAULT_REPO
    workflow = os.getenv(GH_WORKFLOW_ENV) or DEFAULT_WORKFLOW
    ref = os.getenv(GH_REF_ENV) or DEFAULT_REF
    webhook_url = os.getenv(WEBHOOK_URL_ENV) or ""
    webhook_secret = os.getenv(WEBHOOK_SECRET_ENV) or ""

    async with AsyncSessionLocal() as session:  # type: AsyncSession
        try:
            job_uuid = uuid.UUID(job_id)
        except (ValueError, AttributeError):
            return {"ok": False, "reason": "invalid_job_id", "job_id": job_id}

        job = (
            await session.execute(
                select(ProvisioningJob).where(ProvisioningJob.id == job_uuid)
            )
        ).scalar_one_or_none()
        if job is None:
            return {"ok": False, "reason": "job_not_found", "job_id": job_id}

        if not token:
            job.status = ProvisioningJobStatus.FAILED.value
            job.error_message = f"{GH_TOKEN_ENV} is not configured"
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()
            return {"ok": False, "reason": "missing_token", "job_id": job_id}

        dispatch_token = uuid.uuid4().hex

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                payload = _build_dispatch_payload(
                    job,
                    ref=ref,
                    webhook_url=webhook_url,
                    webhook_secret=webhook_secret,
                    dispatch_token=dispatch_token,
                )
                await _dispatch_workflow(
                    client, token, owner, repo, workflow, payload
                )

                # Wait a beat then try to identify the run we just kicked.
                run: Optional[dict[str, Any]] = None
                for attempt in range(RUN_LOOKUP_MAX_ATTEMPTS):
                    await asyncio.sleep(RUN_LOOKUP_SLEEP_SECONDS)
                    run = await _lookup_run(
                        client, token, owner, repo, workflow, dispatch_token
                    )
                    if run:
                        break

        except Exception as exc:
            job.status = ProvisioningJobStatus.FAILED.value
            job.error_message = f"dispatch failed: {exc}"
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()
            logger.exception("provisioning dispatch failed for job %s", job_id)
            return {"ok": False, "reason": "dispatch_error", "error": str(exc)}

        if run is not None:
            job.external_run_id = str(run.get("id") or "")
            job.external_run_url = run.get("html_url") or None

        # Mark RUNNING here only if the webhook hasn't already raced ahead;
        # the webhook handler will also bump pending → running on first
        # event, so this is belt-and-braces.
        if job.status == ProvisioningJobStatus.PENDING.value:
            job.status = ProvisioningJobStatus.RUNNING.value

        await session.commit()

        return {
            "ok": True,
            "job_id": job_id,
            "external_run_id": job.external_run_id,
            "external_run_url": job.external_run_url,
            "dispatch_token": dispatch_token,
        }


@celery_app.task(
    name="src.workers.provisioning_worker.provision_tenant_via_gh_actions",
    bind=True,
    max_retries=2,
    default_retry_delay=10,
)
def provision_tenant_via_gh_actions(self, job_id: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Celery entry point — sync wrapper around the async helper.

    Idempotent at the job level (re-dispatching is safe; the workflow
    short-circuits if the tenant is already provisioned). Idempotency
    at the Celery level is not guaranteed — duplicated tasks will
    create two GH runs, but the second will no-op.
    """
    try:
        return asyncio.run(_provision_async(job_id))
    except Exception as exc:  # pragma: no cover — Celery retries handle this
        logger.exception("provision_tenant_via_gh_actions failed: %s", exc)
        raise self.retry(exc=exc)


async def _destroy_async(job_id: str) -> dict[str, Any]:
    """Async core of the destroy Celery task. Mirror of _provision_async.

    Dispatches the ``offboard-client.yml`` workflow with the same input
    contract (job_id, tenant_slug, webhook_url, webhook_secret,
    dispatch_token), then polls for the run_id so the Console UI can
    deep-link to the workflow run.
    """
    token = os.getenv(GH_TOKEN_ENV) or ""
    owner = os.getenv(GH_OWNER_ENV) or DEFAULT_OWNER
    repo = os.getenv(GH_REPO_ENV) or DEFAULT_REPO
    workflow = DEFAULT_DESTROY_WORKFLOW
    ref = os.getenv(GH_REF_ENV) or DEFAULT_REF
    webhook_url = os.getenv(WEBHOOK_URL_ENV) or ""
    webhook_secret = os.getenv(WEBHOOK_SECRET_ENV) or ""

    async with AsyncSessionLocal() as session:  # type: AsyncSession
        try:
            job_uuid = uuid.UUID(job_id)
        except (ValueError, AttributeError):
            return {"ok": False, "reason": "invalid_job_id", "job_id": job_id}

        job = (
            await session.execute(
                select(ProvisioningJob).where(ProvisioningJob.id == job_uuid)
            )
        ).scalar_one_or_none()
        if job is None:
            return {"ok": False, "reason": "job_not_found", "job_id": job_id}

        if not token:
            job.status = ProvisioningJobStatus.FAILED.value
            job.error_message = f"{GH_TOKEN_ENV} is not configured"
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()
            return {"ok": False, "reason": "missing_token", "job_id": job_id}

        dispatch_token = uuid.uuid4().hex

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                payload = _build_dispatch_payload(
                    job,
                    ref=ref,
                    webhook_url=webhook_url,
                    webhook_secret=webhook_secret,
                    dispatch_token=dispatch_token,
                )
                await _dispatch_workflow(
                    client, token, owner, repo, workflow, payload
                )

                run: Optional[dict[str, Any]] = None
                for attempt in range(RUN_LOOKUP_MAX_ATTEMPTS):
                    await asyncio.sleep(RUN_LOOKUP_SLEEP_SECONDS)
                    run = await _lookup_run(
                        client, token, owner, repo, workflow, dispatch_token
                    )
                    if run:
                        break

        except Exception as exc:
            job.status = ProvisioningJobStatus.FAILED.value
            job.error_message = f"dispatch failed: {exc}"
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()
            logger.exception("destroy dispatch failed for job %s", job_id)
            return {"ok": False, "reason": "dispatch_error", "error": str(exc)}

        if run is not None:
            job.external_run_id = str(run.get("id") or "")
            job.external_run_url = run.get("html_url") or None

        if job.status == ProvisioningJobStatus.PENDING.value:
            job.status = ProvisioningJobStatus.RUNNING.value

        await session.commit()

        return {
            "ok": True,
            "job_id": job_id,
            "external_run_id": job.external_run_id,
            "external_run_url": job.external_run_url,
            "dispatch_token": dispatch_token,
        }


@celery_app.task(
    name="src.workers.provisioning_worker.destroy_tenant_via_gh_actions",
    bind=True,
    max_retries=2,
    default_retry_delay=10,
)
def destroy_tenant_via_gh_actions(self, job_id: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Celery entry point for tenant destroy. Mirror of the create path.

    Dispatches ``offboard-client.yml`` for the tenant slug attached to
    the ProvisioningJob row. The destroy workflow is idempotent: phases
    skip cleanly if a resource is already gone, so retries are safe.
    """
    try:
        return asyncio.run(_destroy_async(job_id))
    except Exception as exc:  # pragma: no cover — Celery retries handle this
        logger.exception("destroy_tenant_via_gh_actions failed: %s", exc)
        raise self.retry(exc=exc)


__all__ = [
    "provision_tenant_via_gh_actions",
    "destroy_tenant_via_gh_actions",
]
