"""Tests for the tenant tier-change endpoint.

Covers the GBT-pre-deploy invariants (2026-05-30):

* ``pilot`` is gone — ``starter`` is the cheapest tier on the registry.
* Tier change updates the tier label + rate limits.
* Tier change updates ``capacity_limits`` when ``apply_preset=true``,
  preserves them when ``apply_preset=false``.
* Downgrade is refused with HTTP 422 when ``capacity_used`` exceeds
  the new tier's preset caps (per-dimension breakdown returned).
* Downgrade override path: ``apply_preset=false`` bypasses the
  capacity check intentionally (contractual override).
* Audit log records both success and the 422-failure case.
* Idempotency: re-applying the same tier does not write a new
  ``CHANGE_TIER`` audit entry.

A quirk worth knowing: the global ``http_exception_handler`` in
``src.core.errors.handlers`` wraps every HTTPException detail into
``{"code", "correlation_id", "message"}`` and stringifies the original
detail. ``_unwrap_error_message`` below recovers the structured dict
the endpoint actually returned via ``ast.literal_eval``.
"""

from __future__ import annotations

import ast
import uuid
from typing import Any, Dict

import pytest
from sqlalchemy import select

from src.api.console_auth import require_sky_team
from src.api.deps import get_current_user
from src.main import app
from src.models.tenant import Tenant, TenantTier
from src.models.user import User
from src.services import pricing_tiers


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def sky_team_dev_bypass(monkeypatch):
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
    app.dependency_overrides[get_current_user] = lambda: sky_team_user
    app.dependency_overrides[require_sky_team] = lambda: sky_team_user
    yield client
    app.dependency_overrides.pop(require_sky_team, None)


def _unwrap_error_message(body: Dict[str, Any]) -> Dict[str, Any]:
    """Recover the structured error dict the endpoint returned.

    The global handler at ``src/core/errors/handlers.py`` packages the
    response as ``{"error": {"code", "message", "correlation_id"}}``
    where ``message`` is ``str(original_detail)``. For a dict detail
    that string is the Python repr — ``ast.literal_eval`` round-trips
    it back to the dict.
    """
    # The handler envelope nests under ``error``.
    if isinstance(body, dict):
        envelope = body.get("error")
        if isinstance(envelope, dict):
            msg = envelope.get("message")
            if isinstance(msg, str) and msg.startswith("{"):
                try:
                    return ast.literal_eval(msg)
                except Exception:  # noqa: BLE001
                    pass
            # Envelope without a parseable message — return it raw.
            return envelope
        # Raw detail dict (no envelope).
        if "error" in body and isinstance(body["error"], str):
            return body
    return body


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


# ── Rename invariants ──────────────────────────────────────────────


def test_starter_is_cheapest_tier():
    """The ``pilot`` slug must no longer be a TIER_REGISTRY key — it
    was renamed to ``starter`` in the 2026-05-30 rename."""
    assert "pilot" not in pricing_tiers.TIER_REGISTRY
    assert "starter" in pricing_tiers.TIER_REGISTRY

    cheapest = pricing_tiers.list_tiers()[0]
    assert cheapest.slug == "starter"
    assert cheapest.display_name == "Starter"


def test_tenant_tier_enum_uses_starter():
    """The ORM enum was updated alongside the registry. ``PILOT`` is
    gone; ``STARTER`` is the canonical lowest tier."""
    assert not hasattr(TenantTier, "PILOT")
    assert TenantTier.STARTER.value == "starter"


# ── Listing tiers ──────────────────────────────────────────────────


def test_list_tiers_returns_starter(authed_client):
    res = authed_client.get("/api/console/v1/tiers")
    assert res.status_code == 200
    slugs = [t["slug"] for t in res.json()]
    assert slugs[0] == "starter"
    assert "pilot" not in slugs


# ── Happy path: upgrade ────────────────────────────────────────────


def test_change_tier_starter_to_foundation_updates_caps(authed_client):
    authed_client.post(
        "/api/console/v1/tenants", json=_registry_payload("up", tier="starter")
    )
    res = authed_client.post(
        "/api/console/v1/tenants/up/tier",
        json={"tier": "foundation", "apply_preset": True},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tier"] == "foundation"
    foundation = pricing_tiers.get_tier("foundation")
    assert body["capacity_limits"] == foundation.capacity_limits
    assert body["rate_limit_rpm"] == foundation.rate_limit_rpm
    assert body["rate_limit_tpm"] == foundation.rate_limit_tpm


def test_change_tier_writes_audit(authed_client):
    authed_client.post(
        "/api/console/v1/tenants", json=_registry_payload("aud", tier="starter")
    )
    authed_client.post(
        "/api/console/v1/tenants/aud/tier",
        json={"tier": "foundation", "apply_preset": True},
    )
    audit = authed_client.get("/api/console/v1/audit?tenant_slug=aud").json()
    change_entries = [e for e in audit if e["action"] == "change_tier"]
    assert len(change_entries) == 1
    payload = change_entries[0]["request_payload"]
    assert payload["from"] == "starter"
    assert payload["to"] == "foundation"


# ── apply_preset=false keeps caps ──────────────────────────────────


def test_change_tier_preserves_caps_when_apply_preset_false(authed_client):
    authed_client.post(
        "/api/console/v1/tenants", json=_registry_payload("keep", tier="starter")
    )
    # Bump the limits manually first.
    authed_client.patch(
        "/api/console/v1/tenants/keep/capacity_limits",
        json={"agents": 99, "sources": 99, "indexed_gb": 999},
    )
    # Then change tier WITHOUT applying preset.
    res = authed_client.post(
        "/api/console/v1/tenants/keep/tier",
        json={"tier": "foundation", "apply_preset": False},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tier"] == "foundation"
    # The custom override survives.
    assert body["capacity_limits"]["agents"] == 99
    assert body["capacity_limits"]["sources"] == 99
    assert body["capacity_limits"]["indexed_gb"] == 999


# ── Downgrade safety ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_downgrade_rejected_when_usage_exceeds_new_caps(
    authed_client, db_session
):
    """Tenant on Foundation with 15 agents in use → downgrade to
    Starter (cap=3) must fail with 422 and list the breaches."""
    authed_client.post(
        "/api/console/v1/tenants",
        json=_registry_payload("over", tier="foundation"),
    )
    # Simulate usage by writing capacity_used directly — the daily
    # bookkeeping job would normally do this.
    row = (
        await db_session.execute(select(Tenant).where(Tenant.slug == "over"))
    ).scalar_one()
    row.capacity_used = {"agents": 15, "sources": 2, "indexed_gb": 1}
    await db_session.commit()

    res = authed_client.post(
        "/api/console/v1/tenants/over/tier",
        json={"tier": "starter", "apply_preset": True},
    )
    assert res.status_code == 422, res.text
    raw = res.json()
    err = _unwrap_error_message(raw)
    assert err.get("error") == "downgrade_exceeds_new_caps", (
        f"raw={raw!r} err={err!r}"
    )
    assert err["from_tier"] == "foundation"
    assert err["to_tier"] == "starter"
    # Agents is the only breached dimension (15 > 3).
    dims = {b["dimension"]: b for b in err["breaches"]}
    assert "agents" in dims
    assert dims["agents"]["used"] == 15
    assert dims["agents"]["new_cap"] == 3
    assert dims["agents"]["excess"] == 12
    # Sources and indexed_gb are within Starter caps → not listed.
    assert "sources" not in dims
    assert "indexed_gb" not in dims


@pytest.mark.asyncio
async def test_downgrade_bypassed_with_apply_preset_false(
    authed_client, db_session
):
    """``apply_preset=false`` is the contractual-override path — the
    capacity check must not run."""
    authed_client.post(
        "/api/console/v1/tenants",
        json=_registry_payload("hack", tier="foundation"),
    )
    row = (
        await db_session.execute(select(Tenant).where(Tenant.slug == "hack"))
    ).scalar_one()
    row.capacity_used = {"agents": 15, "sources": 2, "indexed_gb": 1}
    await db_session.commit()

    res = authed_client.post(
        "/api/console/v1/tenants/hack/tier",
        json={"tier": "starter", "apply_preset": False},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tier"] == "starter"


@pytest.mark.asyncio
async def test_failed_downgrade_writes_failure_audit(
    authed_client, db_session
):
    authed_client.post(
        "/api/console/v1/tenants",
        json=_registry_payload("audf", tier="foundation"),
    )
    row = (
        await db_session.execute(select(Tenant).where(Tenant.slug == "audf"))
    ).scalar_one()
    row.capacity_used = {"agents": 15, "sources": 0, "indexed_gb": 0}
    await db_session.commit()

    authed_client.post(
        "/api/console/v1/tenants/audf/tier",
        json={"tier": "starter", "apply_preset": True},
    )
    audit = authed_client.get("/api/console/v1/audit?tenant_slug=audf").json()
    failed = [
        e
        for e in audit
        if e["action"] == "change_tier" and e["result"] == "failure"
    ]
    assert len(failed) == 1
    payload = failed[0]["request_payload"]
    assert payload["reason"] == "downgrade_exceeds_new_caps"
    assert any(b["dimension"] == "agents" for b in payload["breaches"])


# ── Unknown tier / tenant ──────────────────────────────────────────


def test_unknown_tier_400(authed_client):
    authed_client.post(
        "/api/console/v1/tenants", json=_registry_payload("u", tier="starter")
    )
    res = authed_client.post(
        "/api/console/v1/tenants/u/tier",
        json={"tier": "not-a-real-tier", "apply_preset": True},
    )
    assert res.status_code == 400


def test_unknown_tenant_404(authed_client):
    res = authed_client.post(
        "/api/console/v1/tenants/ghost/tier",
        json={"tier": "starter", "apply_preset": True},
    )
    assert res.status_code == 404


# ── Idempotency: same tier ─────────────────────────────────────────


def test_same_tier_does_not_write_change_audit(authed_client):
    authed_client.post(
        "/api/console/v1/tenants",
        json=_registry_payload("idem", tier="foundation"),
    )
    res = authed_client.post(
        "/api/console/v1/tenants/idem/tier",
        json={"tier": "foundation", "apply_preset": True},
    )
    assert res.status_code == 200
    audit = authed_client.get(
        "/api/console/v1/audit?tenant_slug=idem"
    ).json()
    change_entries = [e for e in audit if e["action"] == "change_tier"]
    # Re-applying the same tier is a no-op for the CHANGE_TIER feed.
    assert change_entries == []
