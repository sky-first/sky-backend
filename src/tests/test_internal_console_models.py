"""Tests for the Internal Console models + schemas (Projeto B PR B#1)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.models.internal_console import (
    AuditAction,
    AuditResult,
    InternalConsoleAudit,
    ProvisioningJob,
    ProvisioningJobStatus,
    ProvisioningJobType,
)
from src.schemas.internal_console import (
    AuditEntryRead,
    ConsoleTenantSummary,
    CreateTenantRequest,
    DestroyTenantRequest,
    ProvisioningJobRead,
)


# ── ORM round-trip ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_row_roundtrips(db_session):
    row = InternalConsoleAudit(
        id=uuid.uuid4(),
        actor_email="lucas@skyfirstlabs.com",
        actor_ip="192.168.1.10",
        action=AuditAction.CREATE_TENANT.value,
        tenant_slug="gbt",
        request_payload={"display_name": "GBT S.A."},
        result=AuditResult.SUCCESS.value,
        result_details={"tenant_id": str(uuid.uuid4())},
    )
    db_session.add(row)
    await db_session.commit()

    fetched = (
        await db_session.execute(
            select(InternalConsoleAudit).where(
                InternalConsoleAudit.actor_email == "lucas@skyfirstlabs.com"
            )
        )
    ).scalar_one()

    assert fetched.action == "create_tenant"
    assert fetched.tenant_slug == "gbt"
    assert fetched.result == "success"
    AuditEntryRead.model_validate(fetched)


@pytest.mark.asyncio
async def test_audit_rejects_unknown_action(db_session):
    row = InternalConsoleAudit(
        id=uuid.uuid4(),
        actor_email="x@skyfirstlabs.com",
        action="invalid_action",
        tenant_slug="gbt",
        result="success",
    )
    db_session.add(row)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_audit_rejects_unknown_result(db_session):
    row = InternalConsoleAudit(
        id=uuid.uuid4(),
        actor_email="x@skyfirstlabs.com",
        action="view_tenant",
        result="maybe",
    )
    db_session.add(row)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_provisioning_job_roundtrips(db_session):
    job = ProvisioningJob(
        id=uuid.uuid4(),
        tenant_slug="gbt",
        actor_email="lucas@skyfirstlabs.com",
        job_type=ProvisioningJobType.CREATE.value,
        status=ProvisioningJobStatus.PENDING.value,
        request_payload={"tier": "starter"},
    )
    db_session.add(job)
    await db_session.commit()

    fetched = (
        await db_session.execute(
            select(ProvisioningJob).where(ProvisioningJob.tenant_slug == "gbt")
        )
    ).scalar_one()
    assert fetched.job_type == "create"
    assert fetched.status == "pending"
    ProvisioningJobRead.model_validate(fetched)


@pytest.mark.asyncio
async def test_provisioning_job_status_check(db_session):
    job = ProvisioningJob(
        id=uuid.uuid4(),
        tenant_slug="gbt",
        actor_email="x@skyfirstlabs.com",
        job_type="create",
        status="not_a_real_status",
    )
    db_session.add(job)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ── Pydantic schemas ───────────────────────────────────────────────


class TestCreateTenantRequest:
    def _base_payload(self):
        return dict(
            slug="gbt",
            display_name="GBT S.A.",
            tier="starter",
            db_host="postgres-gbt.local",
            db_name="tenant_gbt",
            db_credentials_secret_arn="arn:x",
            redis_host="redis-gbt.local",
            redis_credentials_secret_arn="arn:y",
            sso_provider="google",
        )

    def test_accepts_minimal_payload(self):
        req = CreateTenantRequest(**self._base_payload())
        assert req.slug == "gbt"
        assert req.admin_email is None

    def test_accepts_admin_email(self):
        payload = self._base_payload()
        payload["admin_email"] = "admin@gbt.example.com"
        req = CreateTenantRequest(**payload)
        assert req.admin_email == "admin@gbt.example.com"

    def test_inherits_slug_regex_validation(self):
        payload = self._base_payload()
        payload["slug"] = "INVALID UPPER"
        with pytest.raises(ValidationError):
            CreateTenantRequest(**payload)


class TestDestroyTenantRequest:
    def test_requires_both_fields(self):
        with pytest.raises(ValidationError):
            DestroyTenantRequest(confirmation_slug="gbt")
        with pytest.raises(ValidationError):
            DestroyTenantRequest(
                confirmation_phrase="I understand this is irreversible"
            )

    def test_accepts_both(self):
        req = DestroyTenantRequest(
            confirmation_slug="gbt",
            confirmation_phrase="I understand this is irreversible",
        )
        assert req.confirmation_slug == "gbt"


class TestConsoleTenantSummary:
    def test_zero_capacity_by_default(self):
        s = ConsoleTenantSummary(
            slug="gbt",
            display_name="GBT",
            tier="starter",
            is_active=True,
            suspended_at=None,
            custom_domain=None,
            created_at=datetime.now(timezone.utc),
        )
        assert s.capacity_pct_agents == 0.0
        assert s.capacity_pct_sources == 0.0
        assert s.capacity_pct_indexed_gb == 0.0
