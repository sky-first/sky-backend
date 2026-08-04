"""Tests for the Internal Console REST API (Projeto B B#2)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict

import pytest
import pytest_asyncio
from fastapi import Depends
from sqlalchemy import select

from src.api.console_auth import require_sky_team
from src.api.deps import get_current_user
from src.main import app
from src.models.internal_console import (
    InternalConsoleAudit,
    ProvisioningJob,
    ProvisioningJobStatus,
    ProvisioningJobType,
)
from src.models.tenant import Tenant
from src.models.tenant_plan_limits import TenantPlanLimits
from src.models.user import User


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def sky_team_dev_bypass(monkeypatch):
    """Every test in this file runs as a Sky-team member."""
    monkeypatch.setenv("CONSOLE_DEV_BYPASS", "true")
    monkeypatch.setenv("CONSOLE_ALLOWED_EMAILS", "")
    # Celery's send_task blocks trying to connect to the broker even when
    # CELERY_BROKER_URL points to memory:// — the app object is already bound
    # to the original URL at import time. Patch it to a no-op so
    # create_tenant / suspend / destroy return immediately without any I/O.
    import src.workers.celery_app as _celery_mod
    monkeypatch.setattr(_celery_mod.celery_app, "send_task", lambda *a, **kw: None)
    # rate_limit_middleware imports get_redis at module level; with REDIS_HOST=""
    # init_redis() falls back to redis://localhost:6379/0 (lazy pool, no ping).
    # The pool is non-None so the "if redis is None" branch is skipped, and
    # redis.incr() then tries to connect to localhost:6379 with no timeout —
    # hanging every test regardless of HTTP method. Returning None from the
    # module-level reference makes the middleware skip rate-limiting entirely.
    import src.api.middleware.rate_limit as _rl_mod

    async def _no_redis():
        return None

    monkeypatch.setattr(_rl_mod, "get_redis", _no_redis)
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


@pytest_asyncio.fixture
async def authed_client(console_async_client, sky_team_user):
    """AsyncClient on localhost (passes console host-guard) with Sky-team overrides.

    Uses console_async_client instead of the sync TestClient because
    prometheus_fastapi_instrumentator v7 middleware is incompatible with
    TestClient's ByteStream when streaming response bodies.
    """
    app.dependency_overrides[get_current_user] = lambda: sky_team_user
    app.dependency_overrides[require_sky_team] = lambda: sky_team_user
    yield console_async_client
    app.dependency_overrides.pop(require_sky_team, None)
    app.dependency_overrides.pop(get_current_user, None)


def _registry_payload(slug: str = "gbt", **overrides) -> Dict:
    base = dict(
        slug=slug,
        display_name=f"{slug.upper()} Co.",
        tier="starter",
        db_host=f"postgres-{slug}.local",
        db_port=5432,
        db_name=f"tenant_{slug}",
        db_credentials_secret_arn=f"arn:secret:{slug}:db",
        redis_host=f"redis-{slug}.local",
        redis_credentials_secret_arn=f"arn:secret:{slug}:redis",
        sso_provider="google",
    )
    base.update(overrides)
    return base


# ── /me ────────────────────────────────────────────────────────────


async def test_me_returns_actor(authed_client):
    res = await authed_client.get("/api/console/v1/me")
    assert res.status_code == 200
    body = res.json()
    assert body["email"] == "lucas@skyfirstlabs.com"
    assert body["is_sky_team"] is True
    assert body["role"] in {"admin", "operator", "read_only"}


# ── /tenants ───────────────────────────────────────────────────────


async def test_list_tenants_empty(authed_client):
    res = await authed_client.get("/api/console/v1/tenants")
    assert res.status_code == 200
    body = res.json()
    assert body == {"items": [], "total": 0}


async def test_create_tenant_201_and_appears_in_list(authed_client):
    payload = _registry_payload("acme")
    res = await authed_client.post("/api/console/v1/tenants", json=payload)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["slug"] == "acme"
    assert body["tier"] == "starter"

    listed = (await authed_client.get("/api/console/v1/tenants")).json()
    assert listed["total"] == 1
    assert listed["items"][0]["slug"] == "acme"


async def test_create_tenant_409_on_duplicate_slug(authed_client):
    payload = _registry_payload("dupe")
    res1 = await authed_client.post("/api/console/v1/tenants", json=payload)
    assert res1.status_code == 201
    res2 = await authed_client.post("/api/console/v1/tenants", json=payload)
    assert res2.status_code == 409


async def test_get_tenant_404_for_missing_slug(authed_client):
    res = await authed_client.get("/api/console/v1/tenants/ghost")
    assert res.status_code == 404


async def test_get_tenant_detail(authed_client):
    await authed_client.post("/api/console/v1/tenants", json=_registry_payload("readme"))
    res = await authed_client.get("/api/console/v1/tenants/readme")
    assert res.status_code == 200
    body = res.json()
    assert body["slug"] == "readme"
    assert "recent_audit" in body
    assert "recent_jobs" in body


async def test_update_tenant_changes_display_name(authed_client):
    await authed_client.post("/api/console/v1/tenants", json=_registry_payload("upd"))
    res = await authed_client.patch(
        "/api/console/v1/tenants/upd",
        json={"display_name": "Updated Display"},
    )
    assert res.status_code == 200
    assert res.json()["display_name"] == "Updated Display"


async def test_update_tenant_rejects_slug_field(authed_client):
    await authed_client.post("/api/console/v1/tenants", json=_registry_payload("imm"))
    res = await authed_client.patch(
        "/api/console/v1/tenants/imm",
        json={"slug": "renamed"},
    )
    assert res.status_code == 422  # TenantUpdate has extra='forbid'


async def test_suspend_then_resume_roundtrip(authed_client):
    await authed_client.post("/api/console/v1/tenants", json=_registry_payload("life"))

    sus = await authed_client.post(
        "/api/console/v1/tenants/life/suspend", json={"reason": "billing"}
    )
    assert sus.status_code == 200
    body = sus.json()
    assert body["job_type"] == "suspend"
    assert body["status"] == "success"

    after_suspend = (await authed_client.get("/api/console/v1/tenants/life")).json()
    assert after_suspend["is_active"] is False
    assert after_suspend["suspended_at"] is not None

    res = await authed_client.post("/api/console/v1/tenants/life/resume")
    assert res.status_code == 200
    assert res.json()["job_type"] == "resume"

    after_resume = (await authed_client.get("/api/console/v1/tenants/life")).json()
    assert after_resume["is_active"] is True
    assert after_resume["suspended_at"] is None


async def test_suspend_unknown_tenant_404(authed_client):
    res = await authed_client.post("/api/console/v1/tenants/ghost/suspend", json={})
    assert res.status_code == 404


# ── Destroy ────────────────────────────────────────────────────────


async def test_destroy_requires_correct_confirmation(authed_client):
    await authed_client.post("/api/console/v1/tenants", json=_registry_payload("kill"))

    # Wrong slug
    res = await authed_client.post(
        "/api/console/v1/tenants/kill/destroy",
        json={
            "confirmation_slug": "wrong",
            "confirmation_phrase": "I understand this is irreversible",
        },
    )
    assert res.status_code == 400

    # Wrong phrase
    res = await authed_client.post(
        "/api/console/v1/tenants/kill/destroy",
        json={
            "confirmation_slug": "kill",
            "confirmation_phrase": "ok do it",
        },
    )
    assert res.status_code == 400

    # Tenant still active
    detail = (await authed_client.get("/api/console/v1/tenants/kill")).json()
    assert detail["is_active"] is True


async def test_destroy_soft_deletes(authed_client):
    await authed_client.post("/api/console/v1/tenants", json=_registry_payload("die"))
    res = await authed_client.post(
        "/api/console/v1/tenants/die/destroy",
        json={
            "confirmation_slug": "die",
            "confirmation_phrase": "I understand this is irreversible",
        },
    )
    assert res.status_code == 200
    assert res.json()["job_type"] == "destroy"

    detail = (await authed_client.get("/api/console/v1/tenants/die")).json()
    assert detail["is_active"] is False
    assert detail["suspended_at"] is not None


# ── Dashboard ──────────────────────────────────────────────────────


async def test_dashboard_summary(authed_client):
    await authed_client.post("/api/console/v1/tenants", json=_registry_payload("alpha"))
    await authed_client.post(
        "/api/console/v1/tenants",
        json=_registry_payload("beta", tier="foundation"),
    )
    await authed_client.post("/api/console/v1/tenants/alpha/suspend", json={})

    res = await authed_client.get("/api/console/v1/dashboard")
    assert res.status_code == 200
    body = res.json()
    assert body["total_tenants"] == 2
    assert body["active_tenants"] == 1
    assert body["suspended_tenants"] == 1
    assert body["tenants_by_tier"]["starter"] == 1
    assert body["tenants_by_tier"]["foundation"] == 1


# ── Audit log ──────────────────────────────────────────────────────


async def test_audit_records_actions(authed_client):
    await authed_client.post("/api/console/v1/tenants", json=_registry_payload("aud"))
    await authed_client.get("/api/console/v1/tenants/aud")
    await authed_client.post("/api/console/v1/tenants/aud/suspend", json={})

    audit = (await authed_client.get("/api/console/v1/audit")).json()
    # At least: create_tenant, view_tenant, suspend_tenant.
    actions = {entry["action"] for entry in audit}
    assert "create_tenant" in actions
    assert "view_tenant" in actions
    assert "suspend_tenant" in actions


async def test_audit_filter_by_tenant(authed_client):
    await authed_client.post("/api/console/v1/tenants", json=_registry_payload("f1"))
    await authed_client.post("/api/console/v1/tenants", json=_registry_payload("f2"))
    await authed_client.get("/api/console/v1/tenants/f1")

    f1_only = (await authed_client.get("/api/console/v1/audit?tenant_slug=f1")).json()
    slugs = {entry["tenant_slug"] for entry in f1_only}
    assert slugs == {"f1"}


# ── Auth distinctions: 401 anonymous vs 403 non-Sky-team ───────────


async def test_anonymous_is_401(console_async_client, monkeypatch):
    """No JWT (no get_current_user override) → 401 unauthenticated.

    Separates the unauthenticated case from the authenticated-but-not-
    Sky-team case so the FE can route the user to /login (re-auth) vs
    /page (access denied) appropriately. See useAccess.tsx.

    Uses console_async_client (base_url=localhost) instead of the sync
    TestClient — prometheus_fastapi_instrumentator v7 is incompatible
    with Starlette's ByteStream when wrapping responses via sync client,
    which turns any upstream error into a 500 before the assert runs.
    """
    monkeypatch.delenv("CONSOLE_DEV_BYPASS", raising=False)
    monkeypatch.delenv("CONSOLE_ALLOWED_EMAILS", raising=False)
    monkeypatch.delenv("CONSOLE_ALLOWED_HOSTS", raising=False)
    # No dependency_overrides — get_current_user runs for real and
    # fails with no Authorization header, surfacing as None inside
    # require_sky_team which raises 401. base_url=localhost satisfies
    # the Console host gate; no explicit Host header needed.
    res = await console_async_client.get("/api/console/v1/me")
    assert res.status_code == 401
    assert "unauthenticated" in res.json()["error"]["message"]


async def test_non_sky_team_is_403(console_async_client, monkeypatch):
    """An authenticated user that isn't on the Sky-team gets 403.

    ``require_sky_team`` calls ``get_current_user`` directly rather
    than via ``Depends`` so the FastAPI override hook does not apply —
    we patch the symbol that ``console_auth`` actually imports instead.
    The fake accepts the new kwargs (``credentials`` + ``db``) that the
    fix-of-2026-05-29 passes through.

    Uses console_async_client to avoid the prometheus v7 / ByteStream
    incompatibility that turns 403 into 500 with the sync TestClient.
    """
    monkeypatch.delenv("CONSOLE_DEV_BYPASS", raising=False)
    monkeypatch.delenv("CONSOLE_ALLOWED_EMAILS", raising=False)
    outsider = User(
        id=uuid.uuid4(),
        email="outsider@example.com",
        password_hash="",
        name="x",
        role="user",
        email_verified=True,
        has_completed_onboarding=True,
        is_sky_operator=False,
    )

    async def _fake_get_current_user(request, credentials=None, db=None):
        return outsider

    monkeypatch.delenv("CONSOLE_ALLOWED_HOSTS", raising=False)
    from src.api import console_auth as _ca
    monkeypatch.setattr(_ca, "get_current_user", _fake_get_current_user)
    res = await console_async_client.get("/api/console/v1/me")
    assert res.status_code == 403
    assert "sky_team_required" in res.json()["error"]["message"]


# ── /health ────────────────────────────────────────────────────────


async def test_health_returns_ok(authed_client):
    res = await authed_client.get("/api/console/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "version" in body


# ── /tenants/{slug}/status ─────────────────────────────────────────


async def test_tenant_status_no_job(authed_client, db_session):
    # Create the tenant directly — going through the API would automatically
    # produce a ProvisioningJob (create_tenant records one), making last_job
    # non-None and defeating the point of this test.
    tenant = Tenant(
        slug="nojob",
        display_name="NoJob Co.",
        tier="starter",
        db_host="postgres-nojob.local",
        db_name="tenant_nojob",
        db_credentials_secret_arn="arn:secret:nojob:db",
        redis_host="redis-nojob.local",
        redis_credentials_secret_arn="arn:secret:nojob:redis",
        sso_provider="google",
    )
    db_session.add(tenant)
    await db_session.commit()

    res = await authed_client.get("/api/console/v1/tenants/nojob/status")
    assert res.status_code == 200
    body = res.json()
    assert body["tenant_slug"] == "nojob"
    assert body["exists"] is True
    assert body["last_job"] is None


async def test_tenant_status_unknown_slug_not_exists(authed_client):
    res = await authed_client.get("/api/console/v1/tenants/doesnotexist/status")
    assert res.status_code == 200
    body = res.json()
    assert body["exists"] is False
    assert body["last_job"] is None


async def test_tenant_status_with_job(authed_client, db_session):
    await authed_client.post("/api/console/v1/tenants", json=_registry_payload("withjob"))
    job = ProvisioningJob(
        id=uuid.uuid4(),
        tenant_slug="withjob",
        actor_email="lucas@skyfirstlabs.com",
        job_type=ProvisioningJobType.CREATE.value,
        status=ProvisioningJobStatus.SUCCESS.value,
        request_payload={"tier": "starter"},
    )
    db_session.add(job)
    await db_session.commit()

    res = await authed_client.get("/api/console/v1/tenants/withjob/status")
    assert res.status_code == 200
    body = res.json()
    assert body["exists"] is True
    assert body["last_job"] is not None
    assert body["last_job"]["status"] == "success"


# ── /tenants/{slug}/runs ───────────────────────────────────────────


async def test_tenant_runs_404_for_missing_slug(authed_client):
    res = await authed_client.get("/api/console/v1/tenants/ghost/runs")
    assert res.status_code == 404


async def test_tenant_runs_empty_for_new_tenant(authed_client, db_session):
    # Create tenant directly so that no ProvisioningJob is produced at
    # creation time (the API route automatically records a "create" job).
    tenant = Tenant(
        slug="noruns",
        display_name="NoRuns Co.",
        tier="starter",
        db_host="postgres-noruns.local",
        db_name="tenant_noruns",
        db_credentials_secret_arn="arn:secret:noruns:db",
        redis_host="redis-noruns.local",
        redis_credentials_secret_arn="arn:secret:noruns:redis",
        sso_provider="google",
    )
    db_session.add(tenant)
    await db_session.commit()

    res = await authed_client.get("/api/console/v1/tenants/noruns/runs")
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == []
    assert body["total"] == 0


async def test_tenant_runs_returns_jobs(authed_client, db_session):
    # Create tenant directly to avoid the implicit "create" ProvisioningJob
    # that the API route records, which would inflate the expected count.
    tenant = Tenant(
        slug="hasruns",
        display_name="HasRuns Co.",
        tier="starter",
        db_host="postgres-hasruns.local",
        db_name="tenant_hasruns",
        db_credentials_secret_arn="arn:secret:hasruns:db",
        redis_host="redis-hasruns.local",
        redis_credentials_secret_arn="arn:secret:hasruns:redis",
        sso_provider="google",
    )
    db_session.add(tenant)
    for _ in range(3):
        job = ProvisioningJob(
            id=uuid.uuid4(),
            tenant_slug="hasruns",
            actor_email="lucas@skyfirstlabs.com",
            job_type=ProvisioningJobType.CREATE.value,
            status=ProvisioningJobStatus.PENDING.value,
            request_payload={},
        )
        db_session.add(job)
    await db_session.commit()

    res = await authed_client.get("/api/console/v1/tenants/hasruns/runs")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3


# ── Capacity metrics from tenant_plan_limits ───────────────────────


async def test_tenant_list_capacity_zero_without_plan_row(authed_client, db_session):
    """When no TenantPlanLimits row exists, capacity fields default to 0."""
    tenant = Tenant(
        slug="noplans",
        display_name="No Plans Co.",
        tier="starter",
        db_host="pg.local",
        db_name="tenant_noplans",
        db_credentials_secret_arn="arn:secret:noplans:db",
        redis_host="redis.local",
        redis_credentials_secret_arn="arn:secret:noplans:redis",
        sso_provider="google",
    )
    db_session.add(tenant)
    await db_session.commit()

    res = await authed_client.get("/api/console/v1/tenants")
    assert res.status_code == 200
    t = next(i for i in res.json()["items"] if i["slug"] == "noplans")
    assert t["capacity_pct_agents"] == 0.0
    assert t["capacity_pct_sources"] == 0.0
    assert t["capacity_pct_indexed_gb"] == 0.0
    assert t["health_score"] == 0


async def test_tenant_list_capacity_reflects_plan_counters(authed_client, db_session):
    """capacity_pct_* and health_score are computed from TenantPlanLimits live counters."""
    tenant = Tenant(
        slug="withplan",
        display_name="With Plan Co.",
        tier="foundation",
        db_host="pg.local",
        db_name="tenant_withplan",
        db_credentials_secret_arn="arn:secret:withplan:db",
        redis_host="redis.local",
        redis_credentials_secret_arn="arn:secret:withplan:redis",
        sso_provider="google",
    )
    db_session.add(tenant)
    await db_session.flush()

    plan = TenantPlanLimits(
        tenant_id=tenant.id,
        tier="foundation",
        max_agents=10,
        max_users=25,
        max_storage_gb=50,
        max_queries_per_month=10_000,
        current_agents=5,
        current_users=10,
        current_storage_bytes=5 * 1_073_741_824,  # 5 GiB of 50 GiB
        current_queries_this_month=6_000,
    )
    db_session.add(plan)
    await db_session.commit()

    res = await authed_client.get("/api/console/v1/tenants")
    assert res.status_code == 200
    t = next(i for i in res.json()["items"] if i["slug"] == "withplan")
    assert t["capacity_pct_agents"] == 50.0      # 5/10
    assert t["capacity_pct_sources"] == 40.0     # 10/25
    assert t["capacity_pct_indexed_gb"] == 10.0  # 5/50
    # health_score: 40% * (5/10) + 60% * (6000/10000) = 20 + 36 = 56
    assert t["health_score"] == 56


async def test_tenant_list_health_score_unlimited_tier(authed_client, db_session):
    """Enterprise tier (max=None) scores full weight as soon as there is usage."""
    tenant = Tenant(
        slug="enterprise",
        display_name="Enterprise Co.",
        tier="strategic",
        db_host="pg.local",
        db_name="tenant_enterprise",
        db_credentials_secret_arn="arn:secret:enterprise:db",
        redis_host="redis.local",
        redis_credentials_secret_arn="arn:secret:enterprise:redis",
        sso_provider="google",
    )
    db_session.add(tenant)
    await db_session.flush()

    plan = TenantPlanLimits(
        tenant_id=tenant.id,
        tier="enterprise",
        max_agents=None,
        max_users=None,
        max_storage_gb=None,
        max_queries_per_month=None,
        current_agents=3,
        current_users=8,
        current_storage_bytes=0,
        current_queries_this_month=500,
    )
    db_session.add(plan)
    await db_session.commit()

    res = await authed_client.get("/api/console/v1/tenants")
    assert res.status_code == 200
    t = next(i for i in res.json()["items"] if i["slug"] == "enterprise")
    # Unlimited ceilings → capacity shown as 0% (no denominator)
    assert t["capacity_pct_agents"] == 0.0
    assert t["capacity_pct_indexed_gb"] == 0.0
    # But health_score gets full credit for both dimensions since usage > 0
    assert t["health_score"] == 100
