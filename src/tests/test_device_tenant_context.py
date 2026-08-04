"""BE-01 · Tenant context for device clients — acceptance suite T-01.1…T-01.8.

Exercised against the *real* code paths, at the same granularity as
``test_tenant_resolver.py``:

  * token minting/verification         → ``src.core.security``
  * signed ``tid`` claims + policy      → ``src.core.device_tenant``
  * central membership registry         → ``src.services.tenant_membership_service``

Each test maps 1:1 to a row in the masterplan's BE-01 use-case table and to
the four acceptance criteria:

  A. an access token carries a signed, immutable ``tid``; tampering
     invalidates the signature                                   → T-01.1, T-01.3
  B. no sub-domain and no ``tid`` → rejected (400), never default → T-01.4
  C. refresh preserves the ``tid``; switching workspace is an
     explicit re-issue                                           → T-01.6, T-01.7
  D. an off-boarded user can no longer resolve to the tenant even
     with an old token (membership re-checked)                   → T-01.2, T-01.8
"""

from __future__ import annotations

import base64
import json
import uuid

import pytest
from jose import JWTError
from sqlalchemy import select

from src.core.device_tenant import (
    DeviceResolution,
    carry_tenant_claims,
    resolve_device_tenant,
    tenant_claims_for_context,
)
from src.core.security import create_access_token, create_refresh_token, verify_token
from src.core.tenant_context import TenantContext
from src.models.tenant import Tenant
from src.models.tenant_membership import TenantMembership  # noqa: F401 — registers table
from src.services.tenant_membership_service import TenantMembershipService

# ─── Helpers ────────────────────────────────────────────────────────────────


def _persist_tenant(session, **overrides) -> Tenant:
    """A registry row, mirroring the helper in ``test_tenant_resolver.py``."""
    base = dict(
        id=uuid.uuid4(),
        slug="acme",
        display_name="Acme S.A.",
        tier="starter",
        db_host="postgres-acme.svc.cluster.local",
        db_port=5432,
        db_name="acme",
        db_credentials_secret_arn="arn:postgres",
        redis_host="redis-acme.svc.cluster.local",
        redis_credentials_secret_arn="arn:redis",
        sso_provider="google",
    )
    base.update(overrides)
    tenant = Tenant(**base)
    session.add(tenant)
    return tenant


def _ctx(tenant: Tenant) -> TenantContext:
    """Inflate a registry row into the context a token is minted for."""
    return TenantContext(
        slug=tenant.slug,
        id=tenant.id,
        tier=tenant.tier,
        display_name=tenant.display_name,
    )


def _mint_access_for(ctx: TenantContext, user_id: uuid.UUID) -> str:
    """What login does: base identity claims + the tenant claims."""
    token_data = {
        "sub": str(user_id),
        "email": "ethan@acme.com",
        "role": "member",
        **tenant_claims_for_context(ctx),
    }
    return create_access_token(token_data)


def _loaders(session, active_ctx_by_id: dict, member_pairs: set):
    """Build the two injected callables ``resolve_device_tenant`` needs,
    backed by the real registry table + membership service."""

    async def load_tenant_by_id(tid: str):
        return active_ctx_by_id.get(str(tid))

    async def is_member(user_id: str, tid: str) -> bool:
        # Prefer the real service (hits the membership table) when the pair
        # was provisioned; the explicit set keeps forged-claim tests hermetic.
        if (str(user_id), str(tid)) in member_pairs:
            return await TenantMembershipService.is_member(session, user_id, tid)
        return False

    return load_tenant_by_id, is_member


def _tamper_claim(token: str, key: str, value: str) -> str:
    """Rewrite one claim in a signed JWT *without* re-signing — the resulting
    token must fail verification (this is what an attacker would try)."""
    header_b64, payload_b64, signature_b64 = token.split(".")

    def _b64d(seg: str) -> bytes:
        return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))

    def _b64e(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    payload = json.loads(_b64d(payload_b64))
    payload[key] = value
    forged = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    return f"{header_b64}.{forged}.{signature_b64}"


# ─── T-01.1 · signed, immutable tid on the access token ─────────────────────


@pytest.mark.asyncio
async def test_t01_1_access_token_carries_signed_tid(db_session):
    tenant_a = _persist_tenant(db_session, slug="acme")
    await db_session.commit()
    user_id = uuid.uuid4()

    token = _mint_access_for(_ctx(tenant_a), user_id)
    payload = verify_token(token)  # signature verified

    assert payload["tid"] == str(tenant_a.id)
    assert payload["tslug"] == "acme"
    assert payload["sub"] == str(user_id)
    assert payload["type"] == "access"


# ─── T-01.2 · a tid=A token can never resolve to tenant B ───────────────────


@pytest.mark.asyncio
async def test_t01_2_token_scoped_to_its_tenant(db_session):
    tenant_a = _persist_tenant(db_session, slug="acme")
    tenant_b = _persist_tenant(db_session, slug="globex")
    await db_session.commit()
    user_id = uuid.uuid4()
    await TenantMembershipService.upsert(db_session, user_id, tenant_a.id, "member")
    await db_session.commit()

    ctx_by_id = {str(tenant_a.id): _ctx(tenant_a), str(tenant_b.id): _ctx(tenant_b)}
    load, is_member = _loaders(db_session, ctx_by_id, {(str(user_id), str(tenant_a.id))})

    # The token carries tid=A → it resolves to A, and only A.
    claims_a = verify_token(_mint_access_for(_ctx(tenant_a), user_id))
    res_a = await resolve_device_tenant(claims_a, load_tenant_by_id=load, is_member=is_member)
    assert res_a.ok and res_a.context.id == tenant_a.id

    # A forged attempt to act as B (member of A, not B) is refused — never B's data.
    forged_b = {**claims_a, "tid": str(tenant_b.id)}
    res_b = await resolve_device_tenant(forged_b, load_tenant_by_id=load, is_member=is_member)
    assert res_b.resolution is DeviceResolution.FORBIDDEN


# ─── T-01.3 · tampering the tid invalidates the signature (401) ─────────────


@pytest.mark.asyncio
async def test_t01_3_tampered_tid_fails_verification(db_session):
    tenant_a = _persist_tenant(db_session, slug="acme")
    await db_session.commit()

    token = _mint_access_for(_ctx(tenant_a), uuid.uuid4())
    forged = _tamper_claim(token, "tid", str(uuid.uuid4()))

    with pytest.raises(JWTError):
        verify_token(forged)  # → the auth middleware turns this into a 401


# ─── T-01.4 · no tid → 400, never the default tenant ───────────────────────


@pytest.mark.asyncio
async def test_t01_4_no_tid_is_rejected_not_defaulted(db_session):
    load, is_member = _loaders(db_session, {}, set())

    # A legacy token with no tenant claim at all.
    legacy_claims = {"sub": str(uuid.uuid4()), "email": "x@y.com", "role": "member"}
    result = await resolve_device_tenant(legacy_claims, load_tenant_by_id=load, is_member=is_member)

    assert result.resolution is DeviceResolution.UNRESOLVED  # caller → HTTP 400
    assert result.reason == "no_tid_claim"
    assert result.context is None  # explicitly NOT the default tenant


# ─── T-01.5 · multi-tenant user lists both workspaces with role ─────────────


@pytest.mark.asyncio
async def test_t01_5_workspaces_lists_both_with_role(db_session):
    tenant_a = _persist_tenant(db_session, slug="acme")
    tenant_b = _persist_tenant(db_session, slug="globex")
    await db_session.commit()
    user_id = uuid.uuid4()

    await TenantMembershipService.upsert(db_session, user_id, tenant_a.id, "owner")
    await TenantMembershipService.upsert(db_session, user_id, tenant_b.id, "member")
    await db_session.commit()

    memberships = await TenantMembershipService.list_for_user(db_session, user_id)
    by_tenant = {str(m.tenant_id): m.role for m in memberships}

    assert len(memberships) == 2
    assert by_tenant[str(tenant_a.id)] == "owner"
    assert by_tenant[str(tenant_b.id)] == "member"


# ─── T-01.6 · switching workspace is an explicit re-issue; old token → A ────


@pytest.mark.asyncio
async def test_t01_6_select_workspace_reissues_old_token_still_scoped(db_session):
    tenant_a = _persist_tenant(db_session, slug="acme")
    tenant_b = _persist_tenant(db_session, slug="globex")
    await db_session.commit()
    user_id = uuid.uuid4()
    await TenantMembershipService.upsert(db_session, user_id, tenant_a.id, "member")
    await TenantMembershipService.upsert(db_session, user_id, tenant_b.id, "member")
    await db_session.commit()

    ctx_by_id = {str(tenant_a.id): _ctx(tenant_a), str(tenant_b.id): _ctx(tenant_b)}
    load, is_member = _loaders(
        db_session,
        ctx_by_id,
        {(str(user_id), str(tenant_a.id)), (str(user_id), str(tenant_b.id))},
    )

    old_token = _mint_access_for(_ctx(tenant_a), user_id)  # tid = A

    # select-workspace(B) → an explicit new token for B.
    new_token = _mint_access_for(_ctx(tenant_b), user_id)  # tid = B
    new_claims = verify_token(new_token)
    res_new = await resolve_device_tenant(new_claims, load_tenant_by_id=load, is_member=is_member)
    assert res_new.ok and res_new.context.id == tenant_b.id  # resolves to B

    # The old token is untouched and STILL only sees A.
    old_claims = verify_token(old_token)
    res_old = await resolve_device_tenant(old_claims, load_tenant_by_id=load, is_member=is_member)
    assert res_old.ok and res_old.context.id == tenant_a.id


# ─── T-01.7 · refresh preserves the tid ─────────────────────────────────────


@pytest.mark.asyncio
async def test_t01_7_refresh_preserves_tid(db_session):
    tenant_a = _persist_tenant(db_session, slug="acme")
    await db_session.commit()
    user_id = uuid.uuid4()

    claims = tenant_claims_for_context(_ctx(tenant_a))
    refresh = create_refresh_token({"sub": str(user_id), **claims})

    # What /auth/refresh does: read the refresh payload, carry the tenant.
    payload = verify_token(refresh, token_type="refresh")
    carried = carry_tenant_claims(payload)
    new_access = create_access_token(
        {"sub": str(user_id), "email": "x@y.com", "role": "member", **carried}
    )

    new_claims = verify_token(new_access)
    assert new_claims["tid"] == str(tenant_a.id)  # same tenant across refresh
    assert new_claims["tslug"] == "acme"


# ─── T-01.8 · off-boarded user, still-valid token → 403 ─────────────────────


@pytest.mark.asyncio
async def test_t01_8_offboarded_user_forbidden_even_with_valid_token(db_session):
    tenant_a = _persist_tenant(db_session, slug="acme")
    await db_session.commit()
    user_id = uuid.uuid4()
    await TenantMembershipService.upsert(db_session, user_id, tenant_a.id, "member")
    await db_session.commit()

    token = _mint_access_for(_ctx(tenant_a), user_id)
    claims = verify_token(token)  # signature still perfectly valid

    async def load(tid):
        return _ctx(tenant_a) if str(tid) == str(tenant_a.id) else None

    async def is_member(uid, tid):
        return await TenantMembershipService.is_member(db_session, uid, tid)

    # Before off-boarding: resolves fine.
    before = await resolve_device_tenant(claims, load_tenant_by_id=load, is_member=is_member)
    assert before.ok

    # Off-board: remove the membership row (the token is untouched).
    await TenantMembershipService.revoke(db_session, user_id, tenant_a.id)
    await db_session.commit()

    after = await resolve_device_tenant(claims, load_tenant_by_id=load, is_member=is_member)
    assert after.resolution is DeviceResolution.FORBIDDEN  # caller → HTTP 403
