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
    # «Sky Start», o nome da PAGINA COMERCIAL — que e o que o cliente le
    # antes de assinar. Este teste fixava «Starter», o nome interno, e por
    # isso acendeu quando o codigo passou a dizer o mesmo que a pagina.
    assert cheapest.display_name == "Sky Start"


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
    # Gap #4 (2026-05-30): error code renamed to ``tier_change_breach``
    # because we now also consider the tenant_plan_limits source.
    assert err.get("error") == "tier_change_breach", (
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
    # As FONTES tambem estouram agora.
    #
    # O Sky Start passou a permitir UMA fonte (a pagina comercial diz 1; o
    # codigo dizia 3), e este cenario tem duas. Nao e o teste que esta
    # errado — e a consequencia de o codigo passar a dizer o mesmo que a
    # pagina, e o guarda apanhou-a.
    assert dims["sources"]["new_cap"] == 1
    assert dims["sources"]["excess"] == 1
    # O armazenamento continua dentro do tecto.
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


# ── Gap #4: tenant_plan_limits is consulted alongside capacity_used ─


def _seed_plan_limits(db_session, tenant_id, **overrides):
    """Helper — sync insert/update of a TenantPlanLimits row.

    Returns nothing; the caller fetches the fresh row through the
    endpoint or by querying the table directly. Defaults to a
    Foundation tier with zero usage so the test only has to set what
    matters for that case.
    """
    from datetime import datetime, timezone
    from src.models.tenant_plan_limits import TIER_LIMITS, TenantPlanLimits

    defaults = dict(
        tenant_id=tenant_id,
        tier="foundation",
        **TIER_LIMITS["foundation"],
        current_agents=0,
        current_users=0,
        current_storage_bytes=0,
        current_queries_this_month=0,
        queries_period_start=datetime.now(timezone.utc),
        last_threshold_alerted={},
    )
    defaults.update(overrides)
    row = TenantPlanLimits(**defaults)
    db_session.add(row)


@pytest.mark.asyncio
async def test_downgrade_blocked_by_plan_limits_agents(
    authed_client, db_session
):
    """capacity_used is in-spec but tenant_plan_limits.current_agents
    is over the new tier cap → 422 with source=tenant_plan_limits."""
    authed_client.post(
        "/api/console/v1/tenants",
        json=_registry_payload("pla", tier="foundation"),
    )
    tenant_row = (
        await db_session.execute(select(Tenant).where(Tenant.slug == "pla"))
    ).scalar_one()
    # capacity_used clean — only plan_limits should trigger.
    tenant_row.capacity_used = {"agents": 0, "sources": 0, "indexed_gb": 0}
    _seed_plan_limits(
        db_session, tenant_row.id, current_agents=8
    )  # starter cap is 3
    await db_session.commit()

    res = authed_client.post(
        "/api/console/v1/tenants/pla/tier",
        json={"tier": "starter", "apply_preset": True},
    )
    assert res.status_code == 422, res.text
    err = _unwrap_error_message(res.json())
    assert err["error"] == "tier_change_breach"
    by_source = {(b["dimension"], b["source"]): b for b in err["breaches"]}
    assert ("agents", "tenant_plan_limits") in by_source
    agents_breach = by_source[("agents", "tenant_plan_limits")]
    assert agents_breach["used"] == 8
    assert agents_breach["new_cap"] == 3
    assert agents_breach["excess"] == 5


@pytest.mark.asyncio
async def test_downgrade_blocked_by_plan_limits_users(
    authed_client, db_session
):
    authed_client.post(
        "/api/console/v1/tenants",
        json=_registry_payload("plu", tier="foundation"),
    )
    tenant_row = (
        await db_session.execute(select(Tenant).where(Tenant.slug == "plu"))
    ).scalar_one()
    tenant_row.capacity_used = {"agents": 0, "sources": 0, "indexed_gb": 0}
    # Foundation users cap = 25; Starter users cap = 5.
    _seed_plan_limits(db_session, tenant_row.id, current_users=20)
    await db_session.commit()

    res = authed_client.post(
        "/api/console/v1/tenants/plu/tier",
        json={"tier": "starter", "apply_preset": True},
    )
    assert res.status_code == 422, res.text
    err = _unwrap_error_message(res.json())
    dims = {(b["dimension"], b["source"]): b for b in err["breaches"]}
    assert ("users", "tenant_plan_limits") in dims
    assert dims[("users", "tenant_plan_limits")]["used"] == 20
    assert dims[("users", "tenant_plan_limits")]["new_cap"] == 5


@pytest.mark.asyncio
async def test_downgrade_blocked_by_plan_limits_storage(
    authed_client, db_session
):
    """current_storage_bytes is converted to GB before comparison."""
    authed_client.post(
        "/api/console/v1/tenants",
        json=_registry_payload("pls", tier="foundation"),
    )
    tenant_row = (
        await db_session.execute(select(Tenant).where(Tenant.slug == "pls"))
    ).scalar_one()
    tenant_row.capacity_used = {"agents": 0, "sources": 0, "indexed_gb": 0}
    # 10 GB of storage in bytes — Starter cap is 5 GB.
    _seed_plan_limits(
        db_session,
        tenant_row.id,
        current_storage_bytes=10 * 1024 * 1024 * 1024,
    )
    await db_session.commit()

    res = authed_client.post(
        "/api/console/v1/tenants/pls/tier",
        json={"tier": "starter", "apply_preset": True},
    )
    assert res.status_code == 422, res.text
    err = _unwrap_error_message(res.json())
    dims = {(b["dimension"], b["source"]): b for b in err["breaches"]}
    assert ("storage_gb", "tenant_plan_limits") in dims
    breach = dims[("storage_gb", "tenant_plan_limits")]
    assert breach["used"] == 10
    assert breach["new_cap"] == 5
    assert breach["excess"] == 5


@pytest.mark.asyncio
async def test_upgrade_clean_updates_plan_limits(
    authed_client, db_session
):
    """A successful tier change must repoint tenant_plan_limits onto
    the new commercial tier with the matching ceilings.

    Starter (max_agents=3) → Foundation (max_agents=10). The plan-
    limits row gets the new ceilings; the counters carry over.
    """
    from src.models.tenant_plan_limits import (
        TIER_LIMITS,
        TenantPlanLimits,
    )

    authed_client.post(
        "/api/console/v1/tenants",
        json=_registry_payload("upg", tier="starter"),
    )
    tenant_row = (
        await db_session.execute(select(Tenant).where(Tenant.slug == "upg"))
    ).scalar_one()
    _seed_plan_limits(
        db_session,
        tenant_row.id,
        tier="starter",
        **TIER_LIMITS["starter"],
        current_agents=2,
    )
    await db_session.commit()

    res = authed_client.post(
        "/api/console/v1/tenants/upg/tier",
        json={"tier": "foundation", "apply_preset": True},
    )
    assert res.status_code == 200, res.text

    # Re-read the plan-limits row.
    pl = (
        await db_session.execute(
            select(TenantPlanLimits).where(
                TenantPlanLimits.tenant_id == tenant_row.id
            )
        )
    ).scalar_one()
    await db_session.refresh(pl)
    assert pl.tier == "foundation"
    assert pl.max_agents == TIER_LIMITS["foundation"]["max_agents"]
    assert pl.max_users == TIER_LIMITS["foundation"]["max_users"]
    assert pl.max_storage_gb == TIER_LIMITS["foundation"]["max_storage_gb"]
    assert (
        pl.max_queries_per_month
        == TIER_LIMITS["foundation"]["max_queries_per_month"]
    )
    # Counter survives the tier flip — customer's actual usage isn't reset.
    assert pl.current_agents == 2


@pytest.mark.asyncio
async def test_change_tier_success_audit_carries_intent(
    authed_client, db_session
):
    """The success audit row records the new ``tier_change_with_plan_limits``
    intent so the security audit can verify Gap #4 is wired up."""
    authed_client.post(
        "/api/console/v1/tenants",
        json=_registry_payload("intent", tier="starter"),
    )
    res = authed_client.post(
        "/api/console/v1/tenants/intent/tier",
        json={"tier": "foundation", "apply_preset": True},
    )
    assert res.status_code == 200, res.text
    audit = authed_client.get(
        "/api/console/v1/audit?tenant_slug=intent"
    ).json()
    change_entries = [e for e in audit if e["action"] == "change_tier"]
    assert len(change_entries) == 1
    payload = change_entries[0]["request_payload"]
    assert payload.get("intent") == "tier_change_with_plan_limits"
    assert payload.get("commercial_tier") == "foundation"
