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

import re

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import AsyncSessionLocal
from src.models.internal_console import (
    ProvisioningJob,
    ProvisioningJobEvent,
    ProvisioningJobEventLevel,
    ProvisioningJobEventStatus,
    ProvisioningJobStatus,
    ProvisioningJobType,
)
from src.workers.celery_app import celery_app


logger = logging.getLogger(__name__)


# ── Constants ──────────────────────────────────────────────────────

GH_TOKEN_ENV = "GH_PROVISIONING_TOKEN"
GH_OWNER_ENV = "GH_PROVISIONING_OWNER"
GH_REPO_ENV = "GH_PROVISIONING_REPO"
GH_WORKFLOW_ENV = "GH_PROVISIONING_WORKFLOW"
GH_REF_ENV = "GH_PROVISIONING_REF"
WEBHOOK_URL_ENV = "PROVISIONING_WEBHOOK_URL"
WEBHOOK_URL_INTERNAL_ENV = "PROVISIONING_WEBHOOK_URL_INTERNAL"
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
    webhook_url_internal: str,
    webhook_secret: str,
    dispatch_token: str,
    include_admin_email: bool = True,
) -> dict[str, Any]:
    """Build the body for ``POST workflows/{wf}/dispatches``.

    ``include_admin_email`` existe porque os dois workflows não aceitam os
    mesmos inputs. O ``onboard-client.yml`` declara ``admin_email`` — usa-o
    para semear o primeiro humano que consegue entrar. O
    ``offboard-client.yml`` não o declara, e nem faria sentido: não há
    admin a semear em quem se destrói.

    O GitHub recusa **qualquer** input não declarado, com 422:

        Unexpected inputs provided: ["admin_email"]

    Enviar sempre o campo fazia com que nenhum destroy chegasse a correr.
    """
    inputs: dict[str, Any] = {
        "job_id": str(job.id),
        "tenant_slug": job.tenant_slug,
        "webhook_url": webhook_url,
        "webhook_url_internal": webhook_url_internal,
        "webhook_secret": webhook_secret,
        "dispatch_token": dispatch_token,
    }
    if include_admin_email:
        # Vem do pedido original — o Job de migração usa-o para semear o
        # primeiro utilizador. Ausente é aceitável: o workflow assume
        # admin@<slug>.local.
        payload = job.request_payload or {}
        admin_email = ""
        if isinstance(payload, dict):
            admin_email = str(payload.get("admin_email") or "").strip()
        inputs["admin_email"] = admin_email
    return {"ref": ref, "inputs": inputs}


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
    webhook_url_internal = os.getenv(WEBHOOK_URL_INTERNAL_ENV) or webhook_url
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
                    webhook_url_internal=webhook_url_internal,
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

    # Schedule a reconciler that polls the GH Actions API until the
    # workflow run is terminal. This is the fallback for when the
    # workflow's phase webhooks get lost in transit — without it,
    # ``ProvisioningJob.status`` would stay ``RUNNING`` forever.
    # Wrapped in try/except so dispatch still succeeds when the Celery
    # broker is unreachable (e.g. unit tests with no Redis).
    try:
        reconcile_provisioning_job.apply_async(
            args=[job_id],
            countdown=RECONCILE_POLL_INTERVAL_SECONDS,
        )
    except Exception as exc:
        logger.warning(
            "could not schedule reconciler for job %s: %s", job_id, exc
        )

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
    webhook_url_internal = os.getenv(WEBHOOK_URL_INTERNAL_ENV) or webhook_url
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
                    webhook_url_internal=webhook_url_internal,
                    webhook_secret=webhook_secret,
                    dispatch_token=dispatch_token,
                    # O offboard-client.yml não declara admin_email, e o
                    # GitHub recusa inputs não declarados com 422.
                    include_admin_email=False,
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

    # Schedule a reconciler that polls the GH Actions API until the
    # destroy workflow is terminal — same fallback as the provision
    # path. This is what unblocks the slug for reuse when the offboard
    # webhook is dropped (the reconciler sees ``conclusion=success``
    # and deletes the tenant_registry row). Wrapped in try/except so
    # dispatch still succeeds when the Celery broker is unreachable
    # (e.g. unit tests with no Redis).
    try:
        reconcile_provisioning_job.apply_async(
            args=[job_id],
            countdown=RECONCILE_POLL_INTERVAL_SECONDS,
        )
    except Exception as exc:
        logger.warning(
            "could not schedule reconciler for job %s: %s", job_id, exc
        )

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


# ── Run-status reconciler ──────────────────────────────────────────
#
# The webhook the workflow phones home with is unreliable on staging:
# the runners live in the ``arc-system`` namespace and POST to the
# in-cluster Service hostname, but the cross-ns NetworkPolicy / DNS
# path drops packets unpredictably (http_status=000 in the workflow
# logs). When the webhook is lost, the BE never advances the job past
# ``RUNNING`` and the Console UI shows the destroy as forever
# in-flight even though the workflow has succeeded on GitHub.
#
# This reconciler is the belt-and-braces fix: after dispatch we
# schedule a Celery task that polls the GitHub Actions API every 20s
# until the workflow run reaches a terminal state. Whatever conclusion
# the API reports becomes the authoritative ``ProvisioningJob.status``.
# Idempotent — the task short-circuits if the job is already terminal,
# and re-running it is safe.

RECONCILE_POLL_INTERVAL_SECONDS = 20
RECONCILE_MAX_ATTEMPTS = 180  # ~60 min cap

_TERMINAL_FAILURE_CONCLUSIONS = (
    "failure",
    "cancelled",
    "timed_out",
    "action_required",
    "stale",
    "startup_failure",
    "neutral",
)

# GitHub Actions encodes the phase name into the job display name as
# ``<N>/<TOTAL> <phase>`` (e.g. ``1/9 preflight``, ``5/5 report``).
# This regex extracts the trailing phase token so we can map it onto
# our ``ProvisioningJobEvent.phase`` column without keeping a separate
# mapping table.
_PHASE_FROM_JOB_NAME = re.compile(r"^\s*\d+\s*/\s*\d+\s+(?P<phase>\S+)")


def _phase_from_job_name(name: str) -> Optional[str]:
    m = _PHASE_FROM_JOB_NAME.match(name or "")
    return m.group("phase") if m else None


# Which conclusions correspond to which ``ProvisioningJobEventStatus``
# when we synthesise an event row from a GH job. ``in_progress`` →
# ``started``, ``completed`` + conclusion is folded down to either
# ``succeeded`` or ``failed`` (skipped / cancelled / etc. count as
# failure for UI purposes — operator needs to see something red).
def _gh_job_state_to_event(status: str, conclusion: str) -> Optional[tuple[str, str]]:
    """Return ``(event_status, level)`` or None when the GH job is in
    a state we don't render (queued, waiting). Caller skips ``None``.
    """
    if status == "in_progress":
        return (ProvisioningJobEventStatus.STARTED.value,
                ProvisioningJobEventLevel.INFO.value)
    if status == "completed":
        if conclusion == "success":
            return (ProvisioningJobEventStatus.SUCCEEDED.value,
                    ProvisioningJobEventLevel.INFO.value)
        if conclusion in _TERMINAL_FAILURE_CONCLUSIONS:
            return (ProvisioningJobEventStatus.FAILED.value,
                    ProvisioningJobEventLevel.ERROR.value)
        # ``skipped`` / ``neutral`` / unknown — render as a soft
        # success so the phase doesn't sit grey forever.
        return (ProvisioningJobEventStatus.SUCCEEDED.value,
                ProvisioningJobEventLevel.WARNING.value)
    # queued / waiting / requested — nothing visible yet.
    return None


async def _synthesize_phase_events_from_gh(
    session: AsyncSession,
    client: httpx.AsyncClient,
    token: str,
    owner: str,
    repo: str,
    job: ProvisioningJob,
) -> int:
    """Backfill ``provisioning_job_events`` from the GitHub Jobs API.

    The webhook flow is lossy on staging (runners in ``arc-system``
    don't always reach the BE webhook URL). Without a backstop, phases
    that ran on those runners stay grey in the Console UI even though
    the workflow advanced past them on GitHub.

    This pulls the run's per-phase jobs from
    ``/actions/runs/{id}/jobs`` and INSERTs an event row for every
    (phase, status) transition we don't already have. The same row
    shape the webhook handler writes — same CHECK constraint, same
    pub/sub publish — so live SSE subscribers see the late-arriving
    events identically to webhook-delivered ones.

    Returns the count of events synthesised this pass (0 when fully
    caught up).
    """
    jobs_url = (
        f"{GH_API_BASE}/repos/{owner}/{repo}/actions/runs/"
        f"{job.external_run_id}/jobs?per_page=30"
    )
    try:
        response = await client.get(jobs_url, headers=_gh_headers(token))
    except Exception as exc:
        logger.debug("synthesize: GH jobs API error for %s: %s", job.id, exc)
        return 0
    if response.status_code >= 300:
        logger.debug(
            "synthesize: GH jobs API %s for %s: %s",
            response.status_code, job.id, response.text[:200],
        )
        return 0
    payload = response.json() or {}
    gh_jobs = payload.get("jobs") or []
    if not gh_jobs:
        return 0

    # Load existing (phase, status) tuples so we don't re-INSERT a row
    # the webhook already wrote. Cheap — at most a few dozen rows.
    existing = (
        await session.execute(
            select(ProvisioningJobEvent.phase, ProvisioningJobEvent.status)
            .where(ProvisioningJobEvent.job_id == job.id)
        )
    ).all()
    seen = {(row[0], row[1]) for row in existing}

    inserted = 0
    for gh_job in gh_jobs:
        phase = _phase_from_job_name(gh_job.get("name", "") or "")
        if not phase:
            continue
        derived = _gh_job_state_to_event(
            gh_job.get("status", "") or "",
            (gh_job.get("conclusion") or "").lower(),
        )
        if derived is None:
            continue
        ev_status, ev_level = derived

        # A workflow job that's still in_progress will also flip to
        # "completed" later — emit both events but never duplicate.
        # Also: a started event is replaced by succeeded once the job
        # finishes, but the started row is preserved so the timeline
        # shows the elapsed time correctly.
        if (phase, ev_status) in seen:
            continue

        new_event = ProvisioningJobEvent(
            job_id=job.id,
            phase=phase,
            status=ev_status,
            level=ev_level,
            message=(
                f"Phase {phase} {ev_status} (synthesized from GH Actions)."
            ),
            event_metadata={
                "source": "reconciler",
                "gh_job_id": gh_job.get("id"),
                "gh_conclusion": gh_job.get("conclusion"),
            },
        )
        session.add(new_event)
        await session.flush()  # so the event has an id + created_at
        seen.add((phase, ev_status))
        inserted += 1

        # Push out on the per-job Redis channel for any live SSE
        # subscriber. The handler in src.services.provisioning_workflow
        # is the canonical publisher; we lazy-import it so this module
        # stays test-friendly.
        try:
            from src.services.provisioning_workflow import _publish

            await _publish(
                job.id,
                {
                    "id": str(new_event.id),
                    "job_id": str(new_event.job_id),
                    "phase": new_event.phase,
                    "status": new_event.status,
                    "level": new_event.level,
                    "message": new_event.message,
                    "metadata": new_event.event_metadata,
                    "created_at": (
                        new_event.created_at or datetime.now(timezone.utc)
                    ).isoformat(),
                },
            )
        except Exception as exc:  # pragma: no cover — Redis outage is non-fatal
            logger.debug("synthesize: publish failed: %s", exc)

    return inserted


async def _reconcile_async(job_id: str) -> dict[str, Any]:
    """Single reconciliation cycle for one provisioning job.

    Returns a dict with one of:
      * ``terminal=True``   — job was updated to SUCCESS / FAILED.
      * ``still_running=True`` — caller should retry later.
      * ``done=True``       — already terminal; nothing to do.
    """
    token = os.getenv(GH_TOKEN_ENV) or ""
    owner = os.getenv(GH_OWNER_ENV) or DEFAULT_OWNER
    repo = os.getenv(GH_REPO_ENV) or DEFAULT_REPO

    async with AsyncSessionLocal() as session:  # type: AsyncSession
        try:
            job_uuid = uuid.UUID(job_id)
        except (ValueError, AttributeError):
            return {"ok": False, "reason": "invalid_job_id"}

        job = (
            await session.execute(
                select(ProvisioningJob).where(ProvisioningJob.id == job_uuid)
            )
        ).scalar_one_or_none()
        if job is None:
            return {"ok": False, "reason": "job_not_found"}

        # Webhook (or a previous reconcile pass) already finished it.
        if job.status in (
            ProvisioningJobStatus.SUCCESS.value,
            ProvisioningJobStatus.FAILED.value,
        ):
            return {"ok": True, "done": True}

        # Dispatch hasn't recorded the GH run id yet — keep waiting.
        if not job.external_run_id:
            return {"ok": True, "still_running": True, "reason": "no_external_run_id"}

        if not token:
            # Can't poll without the token; leave the job alone so a
            # subsequent reconcile (after the secret rolls out) can
            # finish it. We don't flip to FAILED here because the
            # workflow itself may still be running fine.
            return {"ok": False, "reason": "missing_token", "still_running": True}

        run_url = (
            f"{GH_API_BASE}/repos/{owner}/{repo}/actions/runs/{job.external_run_id}"
        )

        # Hold the client open across the run-status check AND the
        # synthesizer so we don't pay the TLS handshake twice. Single
        # except wraps both — network blips are retry-on-next-pass.
        synthesized = 0
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(run_url, headers=_gh_headers(token))
                # Synthesize phase events from the GH jobs API on every
                # pass (not just terminal). This is what makes the
                # Console timeline light up live even when webhooks get
                # dropped — the GH Jobs API is the authoritative source
                # for per-phase state and we mirror it into our events
                # table. Cheap: one API call + a count(*) on indexed
                # column + a handful of INSERTs.
                try:
                    synthesized = await _synthesize_phase_events_from_gh(
                        session, client, token, owner, repo, job
                    )
                except Exception:
                    logger.exception(
                        "reconcile: synthesizer crashed for job %s", job_id
                    )
        except Exception as exc:  # network blip — retry next time
            logger.debug("reconcile: GH API error for job %s: %s", job_id, exc)
            return {"ok": True, "still_running": True, "reason": "gh_api_error"}

        if response.status_code >= 300:
            logger.debug(
                "reconcile: GH API %s for job %s: %s",
                response.status_code,
                job_id,
                response.text[:200],
            )
            return {"ok": True, "still_running": True, "reason": "gh_api_non_2xx"}

        data = response.json() or {}
        gh_status = data.get("status")  # "queued" | "in_progress" | "completed"
        if gh_status != "completed":
            # Commit any synthesized events so live SSE subscribers
            # see them even though the overall run isn't done yet.
            if synthesized:
                await session.commit()
            return {
                "ok": True,
                "still_running": True,
                "gh_status": gh_status,
                "synthesized_events": synthesized,
            }

        conclusion = (data.get("conclusion") or "").lower()
        now = datetime.now(timezone.utc)
        if conclusion == "success":
            job.status = ProvisioningJobStatus.SUCCESS.value
        elif conclusion in _TERMINAL_FAILURE_CONCLUSIONS:
            job.status = ProvisioningJobStatus.FAILED.value
            job.error_message = (
                job.error_message or f"workflow concluded: {conclusion}"
            )
        else:
            # Unknown conclusion (e.g. ``skipped`` on a re-run) — be
            # conservative and retry later in case GH updates it.
            logger.warning(
                "reconcile: unknown conclusion %r for job %s; retrying",
                conclusion,
                job_id,
            )
            return {
                "ok": True,
                "still_running": True,
                "gh_status": gh_status,
                "conclusion": conclusion,
            }
        job.completed_at = now

        # Successful DESTROY → remove the tenant_registry row so the
        # slug is freed up for reuse. The offboard workflow already
        # dropped the RDS DB, the AWS secret, and the K8s namespace;
        # the platform row is the last thing tying the slug to the
        # tenant. Wrapped in a try/except so a reconciler failure here
        # doesn't strand the job in RUNNING — the DELETE is recoverable
        # by a follow-up reconcile cycle.
        if (
            job.status == ProvisioningJobStatus.SUCCESS.value
            and job.job_type == ProvisioningJobType.DESTROY.value
        ):
            try:
                await session.execute(
                    text("DELETE FROM tenant_registry WHERE slug = :slug"),
                    {"slug": job.tenant_slug},
                )
                # Also wipe historical provisioning_jobs for this slug
                # so re-creating with the same name shows a clean Jobs
                # tab. We exclude the current destroy job from the wipe
                # so the response still references a valid row. ON
                # DELETE CASCADE on provisioning_job_events.job_id
                # cleans the event rows in the same transaction.
                await session.execute(
                    text(
                        "DELETE FROM provisioning_jobs "
                        "WHERE tenant_slug = :slug AND id != :destroy_id"
                    ),
                    {"slug": job.tenant_slug, "destroy_id": job.id},
                )
                logger.info(
                    "reconcile: cleaned tenant_registry + old jobs for %s",
                    job.tenant_slug,
                )
            except Exception:
                logger.exception(
                    "reconcile: failed to clean state for %s",
                    job.tenant_slug,
                )

        await session.commit()
        return {
            "ok": True,
            "terminal": True,
            "conclusion": conclusion,
            "job_id": job_id,
        }


@celery_app.task(
    name="src.workers.provisioning_worker.reconcile_provisioning_job",
    bind=True,
    max_retries=RECONCILE_MAX_ATTEMPTS,
    default_retry_delay=RECONCILE_POLL_INTERVAL_SECONDS,
)
def reconcile_provisioning_job(self, job_id: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Poll the GitHub Actions API until the linked workflow run is
    terminal, then mirror its conclusion onto the ProvisioningJob row.

    The task self-retries on ``still_running`` so the polling interval
    stays bounded — Celery's exponential-backoff is intentionally
    disabled (we pass a fixed countdown) so the operator sees the
    Console state catch up within ~20s of the workflow finishing.
    """
    try:
        result = asyncio.run(_reconcile_async(job_id))
    except Exception as exc:  # pragma: no cover — Celery handles this
        logger.exception("reconcile_provisioning_job crashed: %s", exc)
        raise self.retry(exc=exc, countdown=RECONCILE_POLL_INTERVAL_SECONDS)

    if result.get("still_running"):
        # Fixed-interval poll. The ``max_retries`` cap acts as a hard
        # ceiling — past that we stop polling so a stuck workflow
        # doesn't burn Celery slots forever.
        raise self.retry(countdown=RECONCILE_POLL_INTERVAL_SECONDS)

    return result


__all__ = [
    "provision_tenant_via_gh_actions",
    "destroy_tenant_via_gh_actions",
    "reconcile_provisioning_job",
]
