"""BE-01 · Device tenant-claim enforcement over HTTP (G1).

The resolve_device_tenant policy was unit-tested but never wired into the
request path; G1 wires it (deps.enforce_device_tenant on /auth/me + the
insights router) and proves the acceptance rows at the endpoint level:
T-01.2 (isolation), T-01.3 (tamper→401), T-01.4 (no tid→400),
T-01.8 (off-boarded→403).

Multi-tenant resolution reads the registry through AsyncSessionLocal (a
different DB than the test session), so the tenant loader is patched while
membership is seeded in the real test session (what enforce_device_tenant
actually queries).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.config.settings import settings
from src.core.security import create_access_token
from src.core.tenant_context import TenantContext
from src.models.tenant_membership import TenantMembership
from src.tests.acceptance_helpers import assert_auth_matrix, bearer

TID_A = uuid4()
TID_B = uuid4()


def _ctx(tid, slug: str) -> TenantContext:
    return TenantContext(slug=slug, id=tid, tier="starter", display_name=slug)


async def _fake_loader(tenant_id):
    return {
        str(TID_A): _ctx(TID_A, "tenant-a"),
        str(TID_B): _ctx(TID_B, "tenant-b"),
    }.get(str(tenant_id))


def _token(user, tid=None) -> str:
    data = {"sub": str(user.id), "email": user.email, "role": user.role}
    if tid is not None:
        data["tid"] = str(tid)
    return create_access_token(data)


@pytest.fixture
def multi_tenant(monkeypatch):
    """Turn multi-tenant mode on and make the registry resolve TID_A / TID_B."""
    from src.api.middleware import tenant_resolver

    monkeypatch.setattr(settings, "MULTI_TENANT_ENABLED", True)
    monkeypatch.setattr(tenant_resolver, "_load_tenant_by_id", _fake_loader)
    tenant_resolver.clear_tenant_cache()
    yield
    tenant_resolver.clear_tenant_cache()


async def _make_member(db, user, tid) -> None:
    db.add(TenantMembership(user_id=user.id, tenant_id=tid, role="member"))
    await db.commit()


# ─── T-01.3 · a hand-edited tid breaks the signature → 401 ──────────────────
@pytest.mark.asyncio
async def test_t01_3_tampered_tid_is_401(async_client, test_user):
    token = _token(test_user["user"], TID_A)
    header, payload, sig = token.split(".")
    # Flip the last payload char without re-signing → signature no longer matches.
    tampered_payload = payload[:-1] + ("A" if payload[-1] != "A" else "B")
    tampered = f"{header}.{tampered_payload}.{sig}"

    r = await async_client.get("/api/v1/auth/me", headers=bearer(tampered))
    assert r.status_code == 401


# ─── T-01.4 · device request with no tid → 400 (never the default tenant) ───
@pytest.mark.asyncio
async def test_t01_4_no_tid_is_400(async_client, test_user, multi_tenant):
    r = await async_client.get("/api/v1/auth/me", headers=bearer(_token(test_user["user"])))
    assert r.status_code == 400


# ─── T-01.8 · off-boarded user (no membership) with a valid tid → 403 ───────
@pytest.mark.asyncio
async def test_t01_8_offboarded_is_403(async_client, test_user, multi_tenant):
    # No membership row for the user → they were off-boarded from TID_A.
    r = await async_client.get("/api/v1/auth/me", headers=bearer(_token(test_user["user"], TID_A)))
    assert r.status_code == 403


# ─── T-01.2 · a tid the user doesn't belong to can't reach the feed → 403 ───
@pytest.mark.asyncio
async def test_t01_2_wrong_tenant_cannot_read_insights(
    async_client, test_user, db_session, multi_tenant
):
    # The user belongs to A only...
    await _make_member(db_session, test_user["user"], TID_A)
    # ...but presents a token claiming tenant B.
    r = await async_client.get("/api/v1/insights", headers=bearer(_token(test_user["user"], TID_B)))
    assert r.status_code == 403  # never B's rows


@pytest.mark.asyncio
async def test_t01_2_member_reads_own_tenant_feed(
    async_client, test_user, db_session, multi_tenant
):
    await _make_member(db_session, test_user["user"], TID_A)
    r = await async_client.get("/api/v1/insights", headers=bearer(_token(test_user["user"], TID_A)))
    assert r.status_code == 200  # member of A → feed resolves


# ─── §14 auth matrix on the newly-guarded feed endpoint ─────────────────────
@pytest.mark.asyncio
async def test_insights_auth_matrix(async_client, expired_token, invalid_token):
    await assert_auth_matrix(
        async_client,
        "GET",
        "/api/v1/insights",
        expired_token=expired_token,
        invalid_token=invalid_token,
    )


# ─── single-tenant mode stays a strict no-op (no regression) ────────────────
@pytest.mark.asyncio
async def test_single_tenant_mode_is_noop(async_client, test_user):
    # No multi_tenant fixture → MULTI_TENANT_ENABLED is False; a tid-less token
    # must still work exactly as before.
    r = await async_client.get("/api/v1/auth/me", headers=bearer(_token(test_user["user"])))
    assert r.status_code == 200
