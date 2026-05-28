"""Celery worker for tenant provisioning (Projeto A — v1.1).

Picks up CREATE ProvisioningJobs from the platform DB and runs
bootstrap_tenant.py as a subprocess, updating the job status
throughout: PENDING → RUNNING → SUCCESS / FAILED.

A failed job never retries automatically (acks_late=True,
max_retries=0) — operators see FAILED in the Console jobs tab
and can re-trigger manually or run bootstrap_tenant.py directly.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from src.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Root of the repo so subprocess can find scripts/bootstrap_tenant.py
_REPO_ROOT = Path(__file__).parent.parent.parent


@celery_app.task(
    name="provisioning.provision_tenant",
    queue="knowledge",          # dedicated queue, concurrency=4
    acks_late=True,             # only ack after execution completes
    max_retries=0,              # fail loud — ops must investigate
    time_limit=600,             # hard 10-min ceiling for bootstrap
    soft_time_limit=540,        # soft 9-min → SoftTimeLimitExceeded
)
def provision_tenant(job_id: str) -> None:
    """Run bootstrap_tenant.py for the tenant referenced by job_id.

    Updates ProvisioningJob.status in the platform DB throughout.
    """
    asyncio.run(_provision_async(job_id))


async def _provision_async(job_id: str) -> None:
    import os
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from src.models.internal_console import ProvisioningJob, ProvisioningJobStatus
    from src.config.settings import settings

    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        future=True,
        pool_size=2,
        max_overflow=0,
    )
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with SessionLocal() as db:
            job = await db.get(ProvisioningJob, UUID(job_id))
            if job is None:
                logger.error("provision_tenant_job_not_found", extra={"job_id": job_id})
                return
            if job.status != ProvisioningJobStatus.PENDING.value:
                logger.warning(
                    "provision_tenant_job_already_processed",
                    extra={"job_id": job_id, "status": job.status},
                )
                return

            slug = job.tenant_slug
            job.status = ProvisioningJobStatus.RUNNING.value
            await db.commit()
            logger.info("provision_tenant_started", extra={"slug": slug, "job_id": job_id})

        # Run bootstrap_tenant.py as a subprocess so it gets its own
        # fresh SQLAlchemy engine targeting the tenant DB.
        env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
        result = subprocess.run(
            [sys.executable, str(_REPO_ROOT / "scripts" / "bootstrap_tenant.py"), slug],
            capture_output=True,
            text=True,
            timeout=480,   # 8 min — bootstrap includes alembic upgrade
            cwd=str(_REPO_ROOT),
            env=env,
        )

        success = result.returncode == 0
        async with SessionLocal() as db:
            job = await db.get(ProvisioningJob, UUID(job_id))
            if job is None:
                return
            job.completed_at = datetime.now(timezone.utc)
            if success:
                job.status = ProvisioningJobStatus.SUCCESS.value
                job.output = result.stdout[-4000:] if result.stdout else None
                logger.info("provision_tenant_success", extra={"slug": slug})
            else:
                job.status = ProvisioningJobStatus.FAILED.value
                job.output = result.stdout[-2000:] if result.stdout else None
                job.error_message = (
                    f"returncode={result.returncode}\n"
                    f"--- stderr (last 2000 chars) ---\n"
                    f"{result.stderr[-2000:] if result.stderr else ''}"
                )
                logger.error(
                    "provision_tenant_failed",
                    extra={
                        "slug": slug,
                        "returncode": result.returncode,
                        "stderr": result.stderr[-500:] if result.stderr else "",
                    },
                )
            await db.commit()

    finally:
        await engine.dispose()
