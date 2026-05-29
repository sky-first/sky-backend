"""Tests for the Internal Console REST API (Projeto B B#2)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict

import pytest
from fastapi import Depends
from sqlalchemy import select

from src.api.console_auth import require_sky_team
from src.api.deps import get_current_user
from src.main import app
from src.models.internal_console import InternalConsoleAudit, ProvisioningJob
from src.models.tenant import Tenant
from src.models.user import User


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def sky_team_dev_bypass(monkeypatch):
    """Every test in this file runs as a Sky-team member."""
    monkeypatch.setenv("CONSOLE_DEV_BYPASS", "true")
    monkeypatch.setenv("CONSOLE_ALLOWED_EMAILS", "")
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
    """``client`` overrides get_db_session; we additionally override
    get_current_user + require_sky_team so the endpoints get a Sky-team
    actor without requiring a real JWT."""
    app.dependency_overrides[get_current_user] = lambda: sky_team_user
    app.dependency_overrides[require_sky_team] = lambda: sky_team_user
    yield client
    # Clean up overrides specific to this fixture; the client fixture
    # clears everything at teardown anyway.
    app.dependency_overrides.pop(require_sky_team, None)


def _registry_payload(slug: str = "gbt", **overrides) -> Dict:
    base = dict(
        slug=slug,
        display_name=f"{slug.upper()} Co.",
        tier="pilot",
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


def test_me_returns_actor(authed_client):
    res = authed_client.get("/api/console/v1/me")
    assert res.status_code == 200
    body = res.json()
    assert body["email"] == "lucas@skyfirstlabs.com"
    assert body["is_sky_team"] is True
    assert body["role"] in {"admin", "operator", "read_only"}


# ── /tenants ───────────────────────────────────────────────────────


def test_list_tenants_empty(authed_client):
    res = authed_client.get("/api/console/v1/tenants")
    assert res.status_code == 200
    body = res.json()
    assert body == {"items": [], "total": 0}


def test_create_tenant_201_and_appears_in_list(authed_client):
    payload = _registry_payload("acme")
    res = authed_client.post("/api/console/v1/tenants", json=payload)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["slug"] == "acme"
    assert body["tier"] == "pilot"

    listed = authed_client.get("/api/console/v1/tenants").json()
    assert listed["total"] == 1
    assert listed["items"][0]["slug"] == "acme"


def test_create_tenant_409_on_duplicate_slug(authed_client):
    payload = _registry_payload("dupe")
    res1 = authed_client.post("/api/console/v1/tenants", json=payload)
    assert res1.status_code == 201
    res2 = authed_client.post("/api/console/v1/tenants", json=payload)
    assert res2.status_code == 409


def test_get_tenant_404_for_missing_slug(authed_client):
    res = authed_client.get("/api/console/v1/tenants/ghost")
    assert res.status_code == 404


def test_get_tenant_detail(authed_client):
    authed_client.post("/api/console/v1/tenants", json=_registry_payload("readme"))
    res = authed_client.get("/api/console/v1/tenants/readme")
    assert res.status_code == 200
    body = res.json()
    assert body["slug"] == "readme"
    assert "recent_audit" in body
    assert "recent_jobs" in body


def test_update_tenant_changes_display_name(authed_client):
    authed_client.post("/api/console/v1/tenants", json=_registry_payload("upd"))
    res = authed_client.patch(
        "/api/console/v1/tenants/upd",
        json={"display_name": "Updated Display"},
    )
    assert res.status_code == 200
    assert res.json()["display_name"] == "Updated Display"


def test_update_tenant_rejects_slug_field(authed_client):
    authed_client.post("/api/console/v1/tenants", json=_registry_payload("imm"))
    res = authed_client.patch(
        "/api/console/v1/tenants/imm",
        json={"slug": "renamed"},
    )
    assert res.status_code == 422  # TenantUpdate has extra='forbid'


def test_suspend_then_resume_roundtrip(authed_client):
    authed_client.post("/api/console/v1/tenants", json=_registry_payload("life"))

    sus = authed_client.post(
        "/api/console/v1/tenants/life/suspend", json={"reason": "billing"}
    )
    assert sus.status_code == 200
    body = sus.json()
    assert body["job_type"] == "suspend"
    assert body["status"] == "success"

    after_suspend = authed_client.get("/api/console/v1/tenants/life").json()
    assert after_suspend["is_active"] is False
    assert after_suspend["suspended_at"] is not None

    res = authed_client.post("/api/console/v1/tenants/life/resume")
    assert res.status_code == 200
    assert res.json()["job_type"] == "resume"

    after_resume = authed_client.get("/api/console/v1/tenants/life").json()
    assert after_resume["is_active"] is True
    assert after_resume["suspended_at"] is None


def test_suspend_unknown_tenant_404(authed_client):
    res = authed_client.post("/api/console/v1/tenants/ghost/suspend", json={})
    assert res.status_code == 404


# ── Destroy ────────────────────────────────────────────────────────


def test_destroy_requires_correct_confirmation(authed_client):
    authed_client.post("/api/console/v1/tenants", json=_registry_payload("kill"))

    # Wrong slug
    res = authed_client.post(
        "/api/console/v1/tenants/kill/destroy",
        json={
            "confirmation_slug": "wrong",
            "confirmation_phrase": "I understand this is irreversible",
        },
    )
    assert res.status_code == 400

    # Wrong phrase
    res = authed_client.post(
        "/api/console/v1/tenants/kill/destroy",
        json={
            "confirmation_slug": "kill",
            "confirmation_phrase": "ok do it",
        },
    )
    assert res.status_code == 400

    # Tenant still active
    detail = authed_client.get("/api/console/v1/tenants/kill").json()
    assert detail["is_active"] is True


def test_destroy_soft_deletes(authed_client):
    authed_client.post("/api/console/v1/tenants", json=_registry_payload("die"))
    res = authed_client.post(
        "/api/console/v1/tenants/die/destroy",
        json={
            "confirmation_slug": "die",
            "confirmation_phrase": "I understand this is irreversible",
        },
    )
    assert res.status_code == 200
    assert res.json()["job_type"] == "destroy"

    detail = authed_client.get("/api/console/v1/tenants/die").json()
    assert detail["is_active"] is False
    assert detail["suspended_at"] is not None


# ── Dashboard ──────────────────────────────────────────────────────


def test_dashboard_summary(authed_client):
    authed_client.post("/api/console/v1/tenants", json=_registry_payload("alpha"))
    authed_client.post(
        "/api/console/v1/tenants",
        json=_registry_payload("beta", tier="foundation"),
    )
    authed_client.post("/api/console/v1/tenants/alpha/suspend", json={})

    res = authed_client.get("/api/console/v1/dashboard")
    assert res.status_code == 200
    body = res.json()
    assert body["total_tenants"] == 2
    assert body["active_tenants"] == 1
    assert body["suspended_tenants"] == 1
    assert body["tenants_by_tier"]["pilot"] == 1
    assert body["tenants_by_tier"]["foundation"] == 1


# ── Audit log ──────────────────────────────────────────────────────


def test_audit_records_actions(authed_client):
    authed_client.post("/api/console/v1/tenants", json=_registry_payload("aud"))
    authed_client.get("/api/console/v1/tenants/aud")
    authed_client.post("/api/console/v1/tenants/aud/suspend", json={})

    audit = authed_client.get("/api/console/v1/audit").json()
    # At least: create_tenant, view_tenant, suspend_tenant.
    actions = {entry["action"] for entry in audit}
    assert "create_tenant" in actions
    assert "view_tenant" in actions
    assert "suspend_tenant" in actions


def test_audit_filter_by_tenant(authed_client):
    authed_client.post("/api/console/v1/tenants", json=_registry_payload("f1"))
    authed_client.post("/api/console/v1/tenants", json=_registry_payload("f2"))
    authed_client.get("/api/console/v1/tenants/f1")

    f1_only = authed_client.get("/api/console/v1/audit?tenant_slug=f1").json()
    slugs = {entry["tenant_slug"] for entry in f1_only}
    assert slugs == {"f1"}


# ── Auth distinctions: 401 anonymous vs 403 non-Sky-team ───────────


def test_anonymous_is_401(client, monkeypatch):
    """No JWT (no get_current_user override) → 401 unauthenticated.

    Separates the unauthenticated case from the authenticated-but-not-
    Sky-team case so the FE can route the user to /login (re-auth) vs
    /page (access denied) appropriately. See useAccess.tsx.
    """
    monkeypatch.delenv("CONSOLE_DEV_BYPASS", raising=False)
    monkeypatch.delenv("CONSOLE_ALLOWED_EMAILS", raising=False)
    # No dependency_overrides — get_current_user runs for real and
    # fails with no Authorization header, surfacing as None inside
    # require_sky_team which raises 401.
    res = client.get("/api/console/v1/me")
    assert res.status_code == 401
    assert "unauthenticated" in res.json()["error"]["message"]


def test_non_sky_team_is_403(client, monkeypatch):
    """An authenticated user that isn't on the Sky-team gets 403.

    ``require_sky_team`` calls ``get_current_user`` directly rather
    than via ``Depends`` so the FastAPI override hook does not apply —
    we patch the symbol that ``console_auth`` actually imports instead.
    The fake accepts the new kwargs (``credentials`` + ``db``) that the
    fix-of-2026-05-29 passes through.
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

    from src.api import console_auth as _ca
    monkeypatch.setattr(_ca, "get_current_user", _fake_get_current_user)
    res = client.get("/api/console/v1/me")
    assert res.status_code == 403
    assert "sky_team_required" in res.json()["error"]["message"]
