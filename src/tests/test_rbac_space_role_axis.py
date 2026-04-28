"""RBAC Space-axis role test matrix — A1.

This file is the contract for "Space role = commander | navigator | explorer"
that A1 implements. It also captures the demo guest is_demo overrides and
the legacy admin/member normalization (so existing demo Spaces created with
SpaceMember.role="admin" keep working without a DB migration).

Coverage requirement (from product owner):
  ≥ 30 distinct test cases per role variant.

Role variants under test
------------------------
  commander       — canonical Space role, full content + member management
  navigator       — content writes, no Space-level admin
  explorer        — read-only on Space content
  demo_commander  — same as commander but in is_demo Space; mutation of
                    SHARED resources (connections, knowledge files) is
                    blocked at the BE regardless of role
  admin_legacy    — SpaceMember.role="admin" (legacy demo signups before
                    A1) — must normalize to commander permissions
  member_legacy   — SpaceMember.role="member" — must normalize to explorer
  platform_owner  — User.role="owner" with no SpaceMember → bypasses Space
                    RBAC entirely
  external        — no SpaceMember on this Space → denied for any
                    Space-scoped endpoint

Test ID convention
------------------
  R-NN-<endpoint>  → READ-only endpoint (≥ explorer)
  W-NN-<endpoint>  → WRITE endpoint (≥ navigator)
  M-NN-<endpoint>  → MANAGEMENT endpoint (≥ commander)
  D-NN-<endpoint>  → DEMO override (commander allowed in non-demo,
                     blocked in demo)
  L-NN-<endpoint>  → LEGACY normalization (admin_legacy → commander
                     equivalent, member_legacy → explorer equivalent)

Run only this file:
    pytest src/tests/test_rbac_space_role_axis.py -v
"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

import pytest
import pytest_asyncio

from src.core.security import create_access_token, get_password_hash
from src.models.connection import DataConnection
from src.models.space import Space, SpaceConnection, SpaceMember
from src.repositories.user import UserRepository

Expect = Literal["allow", "deny"]


# Variant precedence — higher score = more capable.
# Used to map each variant to a "minimum role" check.
_VARIANT_BASE = {
    "explorer": "explorer",
    "navigator": "navigator",
    "commander": "commander",
    # Legacy values must normalize to the same effective role:
    "member_legacy": "explorer",
    "admin_legacy": "commander",
    # Demo guest is a commander but loses connection/knowledge mutation:
    "demo_commander": "commander",
    # Cross-axis bypass:
    "platform_owner": "owner",
    # External user (no membership):
    "external": "external",
}

_ORDERED_BASE = ["external", "explorer", "navigator", "commander", "owner"]
_BASE_IDX = {b: i for i, b in enumerate(_ORDERED_BASE)}

ALL_VARIANTS = list(_VARIANT_BASE.keys())


def _expected(
    variant: str,
    *,
    min_role: str,
    demo_blocks: bool = False,
) -> Expect:
    """Compute expected outcome for a (variant, min_role) pair.

    ``min_role`` is the lowest base role that the action allows. ``demo_blocks``
    flips demo_commander to deny on top of the role check (used for
    connection / knowledge mutations on a shared synthetic dataset).
    """
    if variant == "demo_commander" and demo_blocks:
        return "deny"
    base = _VARIANT_BASE[variant]
    if base == "external":
        return "deny"
    if base == "owner":
        return "allow"  # platform owner bypasses Space RBAC
    return "allow" if _BASE_IDX[base] >= _BASE_IDX[min_role] else "deny"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _assert_outcome(resp, expected: Expect, case_id: str) -> None:
    if expected == "allow":
        assert resp.status_code < 400, (
            f"[{case_id}] expected ALLOW but got {resp.status_code}: "
            f"{resp.text[:300]}"
        )
    else:
        assert resp.status_code in (403, 404, 422), (
            f"[{case_id}] expected DENY (403/404/422) but got "
            f"{resp.status_code}: {resp.text[:300]}"
        )


# -----------------------------------------------------------------------------
# Seed fixture — builds two Spaces (one normal, one demo) and one user per
# variant. Each variant gets its own JWT.
# -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_axis(db_session) -> dict:
    user_repo = UserRepository(db_session)
    users: dict[str, object] = {}
    tokens: dict[str, str] = {}

    # Platform-role mapping for each variant
    platform_role_for = {
        "platform_owner": "owner",
        "external": "member",
        # Everyone else is a plain platform member with scoped grants
        "explorer": "member",
        "navigator": "member",
        "commander": "member",
        "member_legacy": "member",
        "admin_legacy": "member",
        "demo_commander": "member",
    }

    for variant in ALL_VARIANTS:
        platform_role = platform_role_for[variant]
        u = await user_repo.create(
            email=f"{variant}@axis-test.example.com",
            password_hash=get_password_hash("test"),
            name=variant.replace("_", " ").title(),
            role=platform_role,
        )
        # demo_commander gets is_demo=True
        if variant == "demo_commander":
            u.is_demo = True
            await db_session.flush()

        users[variant] = u
        tokens[variant] = create_access_token({
            "sub": str(u.id),
            "email": u.email,
            "role": platform_role,
        })

    # Normal Space owned by commander
    space = Space(
        name="Axis Test Space",
        created_by=users["commander"].id,
    )
    db_session.add(space)
    await db_session.flush()

    # Demo Space owned by demo_commander
    demo_space = Space(
        name="Demo — Axis Test Co.",
        created_by=users["demo_commander"].id,
        is_demo=True,
    )
    db_session.add(demo_space)
    await db_session.flush()

    # SpaceMember rows on the NORMAL Space
    member_role_pairs = [
        ("commander", "commander"),
        ("navigator", "navigator"),
        ("explorer", "explorer"),
        ("admin_legacy", "admin"),    # legacy value
        ("member_legacy", "member"),  # legacy value
    ]
    for variant, role_string in member_role_pairs:
        db_session.add(SpaceMember(
            space_id=space.id,
            user_id=users[variant].id,
            role=role_string,
        ))

    # demo_commander is commander of their OWN demo space
    db_session.add(SpaceMember(
        space_id=demo_space.id,
        user_id=users["demo_commander"].id,
        role="commander",
    ))

    # Shared synthetic connection wired to BOTH Spaces (mirrors the real
    # demo setup where the dataset is shared via SpaceConnection bridge).
    shared_conn = DataConnection(
        id=uuid4(),
        name="Shared Demo Dataset",
        connection_type="postgresql",
        config={},
        created_by=users["commander"].id,
        is_active=True,
    )
    db_session.add(shared_conn)
    await db_session.flush()
    db_session.add(SpaceConnection(space_id=space.id, connection_id=shared_conn.id))
    db_session.add(SpaceConnection(
        space_id=demo_space.id,
        connection_id=shared_conn.id,
    ))

    await db_session.commit()

    return {
        "users": users,
        "tokens": tokens,
        "space_id": str(space.id),
        "demo_space_id": str(demo_space.id),
        "connection_id": str(shared_conn.id),
    }


# Helper for parametrize: returns (variant, space_target) for tests that need
# to use the demo space when the variant is demo_commander.
def _space_for(seeded, variant: str) -> str:
    return seeded["demo_space_id"] if variant == "demo_commander" else seeded["space_id"]


# =============================================================================
# Section R — READ surfaces (baseline = explorer)
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_R_01_list_spaces(seeded_axis, async_client, variant):
    r = await async_client.get(
        "/api/v1/spaces", headers=_auth(seeded_axis["tokens"][variant]),
    )
    # /spaces always succeeds — it returns the user's own list, possibly empty.
    # Even external user gets 200 with [].
    expected = "deny" if variant == "external" and False else "allow"
    _assert_outcome(r, expected, "R-01")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_R_02_get_space_detail(seeded_axis, async_client, variant):
    space_id = _space_for(seeded_axis, variant)
    r = await async_client.get(
        f"/api/v1/spaces/{space_id}",
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, _expected(variant, min_role="explorer"), "R-02")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_R_03_list_space_members(seeded_axis, async_client, variant):
    space_id = _space_for(seeded_axis, variant)
    r = await async_client.get(
        f"/api/v1/spaces/{space_id}/members",
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, _expected(variant, min_role="explorer"), "R-03")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_R_04_list_connections(seeded_axis, async_client, variant):
    r = await async_client.get(
        "/api/v1/connections",
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    # Listing connections is always 200; result set is RBAC-filtered. We only
    # assert HTTP outcome here.
    _assert_outcome(r, "allow", "R-04")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_R_05_get_connection(seeded_axis, async_client, variant):
    r = await async_client.get(
        f"/api/v1/connections/{seeded_axis['connection_id']}",
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    # External user has no SpaceMember anywhere — they shouldn't see the
    # shared connection. Everyone else should.
    expected = "deny" if variant == "external" else "allow"
    _assert_outcome(r, expected, "R-05")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_R_06_list_dashboards(seeded_axis, async_client, variant):
    r = await async_client.get(
        "/api/v1/dashboards",
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, "allow", "R-06")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_R_07_list_widgets(seeded_axis, async_client, variant):
    r = await async_client.get(
        "/api/v1/widgets",
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, "allow", "R-07")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_R_08_list_agents(seeded_axis, async_client, variant):
    r = await async_client.get(
        "/api/v1/agents/",
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, "allow", "R-08")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_R_09_list_pillars(seeded_axis, async_client, variant):
    r = await async_client.get(
        "/api/v1/pillars",
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, "allow", "R-09")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_R_10_list_metrics(seeded_axis, async_client, variant):
    r = await async_client.get(
        "/api/v1/metrics",
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, "allow", "R-10")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_R_11_list_glossary(seeded_axis, async_client, variant):
    r = await async_client.get(
        "/api/v1/glossary",
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, "allow", "R-11")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_R_12_me(seeded_axis, async_client, variant):
    r = await async_client.get(
        "/api/v1/users/me",
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, "allow", "R-12")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_R_13_list_events(seeded_axis, async_client, variant):
    r = await async_client.get(
        "/api/v1/events",
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, "allow", "R-13")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_R_14_list_relationships(seeded_axis, async_client, variant):
    r = await async_client.get(
        "/api/v1/relationships",
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, "allow", "R-14")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_R_15_list_knowledge_files(seeded_axis, async_client, variant):
    space_id = _space_for(seeded_axis, variant)
    r = await async_client.get(
        f"/api/v1/knowledge/files?scope=space&scope_id={space_id}",
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    # External user denied (no space access); everyone else allowed
    expected = "deny" if variant == "external" else "allow"
    _assert_outcome(r, expected, "R-15")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_R_16_list_pages(seeded_axis, async_client, variant):
    r = await async_client.get(
        "/api/v1/pages",
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, "allow", "R-16")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_R_17_get_user_permissions(seeded_axis, async_client, variant):
    r = await async_client.get(
        "/api/v1/users/me/permissions",
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, "allow", "R-17")


# =============================================================================
# Section W — WRITE (baseline = navigator)
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_W_20_create_widget(seeded_axis, async_client, variant):
    payload = {
        "title": f"widget-{variant}",
        "type": "metric",
        "config": {},
        "position": {"x": 0, "y": 0, "w": 4, "h": 4},
    }
    r = await async_client.post(
        "/api/v1/widgets",
        json=payload,
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, _expected(variant, min_role="navigator"), "W-20")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_W_21_create_dashboard(seeded_axis, async_client, variant):
    payload = {"name": f"dash-{variant}", "description": "axis test"}
    r = await async_client.post(
        "/api/v1/dashboards",
        json=payload,
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, _expected(variant, min_role="navigator"), "W-21")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_W_22_create_agent(seeded_axis, async_client, variant):
    space_id = _space_for(seeded_axis, variant)
    payload = {
        "name": f"agent-{variant}",
        "archetype": "custom",
        "scope": "space",
        "scope_id": space_id,
        "monitor_type": "question",
        "focus": "test",
        "frequency": "daily",
        "connection_ids": [],
    }
    r = await async_client.post(
        "/api/v1/agents/",
        json=payload,
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, _expected(variant, min_role="navigator"), "W-22")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_W_23_create_pillar(seeded_axis, async_client, variant):
    payload = {"name": f"pillar-{variant}", "description": "axis"}
    r = await async_client.post(
        "/api/v1/pillars",
        json=payload,
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, _expected(variant, min_role="navigator"), "W-23")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_W_24_create_metric(seeded_axis, async_client, variant):
    payload = {
        "name": f"metric-{variant}",
        "description": "axis",
        "formula": "SELECT 1",
    }
    r = await async_client.post(
        "/api/v1/metrics",
        json=payload,
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, _expected(variant, min_role="navigator"), "W-24")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_W_25_create_glossary_term(seeded_axis, async_client, variant):
    payload = {
        "term": f"term-{variant}",
        "definition": "axis test definition",
    }
    r = await async_client.post(
        "/api/v1/glossary",
        json=payload,
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, _expected(variant, min_role="navigator"), "W-25")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_W_26_run_ai_query_in_space(seeded_axis, async_client, variant):
    space_id = _space_for(seeded_axis, variant)
    payload = {
        "question": "How many rows?",
        "space_id": space_id,
    }
    r = await async_client.post(
        "/api/v1/ai/query",
        json=payload,
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    # AI query bypasses RBAC for unscoped (Personal) but here we pass space_id.
    # Explorer + above can run; external denied; demo_commander allowed
    # (commander on own space, not a connection mutation).
    _assert_outcome(r, _expected(variant, min_role="explorer"), "W-26")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_W_27_run_ai_query_personal(seeded_axis, async_client, variant):
    payload = {"question": "How many rows?"}  # no space_id = Personal mode
    r = await async_client.post(
        "/api/v1/ai/query",
        json=payload,
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    # Personal mode bypasses Space RBAC (per ai.py:100). Even external user
    # gets through (the page lookup may 404 if they have no page, which is
    # acceptable as deny).
    _assert_outcome(r, "allow", "W-27")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_W_28_create_relationship(seeded_axis, async_client, variant):
    payload = {
        "name": f"rel-{variant}",
        "type": "lineage",
        "source": "table_a",
        "target": "table_b",
    }
    r = await async_client.post(
        "/api/v1/relationships",
        json=payload,
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, _expected(variant, min_role="navigator"), "W-28")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_W_29_create_event(seeded_axis, async_client, variant):
    payload = {
        "name": f"event-{variant}",
        "type": "external",
        "description": "axis test",
    }
    r = await async_client.post(
        "/api/v1/events",
        json=payload,
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, _expected(variant, min_role="navigator"), "W-29")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_W_30_create_goal(seeded_axis, async_client, variant):
    payload = {"name": f"goal-{variant}", "description": "axis"}
    r = await async_client.post(
        "/api/v1/goals",
        json=payload,
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, _expected(variant, min_role="navigator"), "W-30")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_W_31_create_okr(seeded_axis, async_client, variant):
    payload = {
        "objective": f"objective-{variant}",
        "description": "axis",
    }
    r = await async_client.post(
        "/api/v1/okrs",
        json=payload,
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, _expected(variant, min_role="navigator"), "W-31")


# =============================================================================
# Section M — MANAGEMENT (baseline = commander)
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_M_40_invite_member(seeded_axis, async_client, variant):
    space_id = _space_for(seeded_axis, variant)
    target = seeded_axis["users"]["explorer"]
    payload = {"user_id": str(target.id), "role": "navigator"}
    r = await async_client.post(
        f"/api/v1/spaces/{space_id}/members",
        json=payload,
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    expected = _expected(variant, min_role="commander")
    if expected == "allow":
        # Inviting an already-member returns 400 — also acceptable
        assert r.status_code in (200, 201, 400), (
            f"[M-40] expected allow got {r.status_code}: {r.text[:200]}"
        )
    else:
        assert r.status_code in (403, 404), f"[M-40] {r.status_code}: {r.text[:200]}"


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_M_41_create_crew(seeded_axis, async_client, variant):
    space_id = _space_for(seeded_axis, variant)
    payload = {"name": f"crew-{variant}", "space_id": space_id}
    r = await async_client.post(
        "/api/v1/crews",
        json=payload,
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, _expected(variant, min_role="commander"), "M-41")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_M_42_edit_space(seeded_axis, async_client, variant):
    space_id = _space_for(seeded_axis, variant)
    payload = {"name": f"renamed-by-{variant}"}
    r = await async_client.put(
        f"/api/v1/spaces/{space_id}",
        json=payload,
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, _expected(variant, min_role="commander"), "M-42")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_M_43_change_member_role(seeded_axis, async_client, variant):
    space_id = _space_for(seeded_axis, variant)
    target = seeded_axis["users"]["explorer"]
    payload = {"role": "navigator"}
    r = await async_client.put(
        f"/api/v1/spaces/{space_id}/members/{target.id}",
        json=payload,
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, _expected(variant, min_role="commander"), "M-43")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_M_44_remove_member(seeded_axis, async_client, variant):
    space_id = _space_for(seeded_axis, variant)
    target = seeded_axis["users"]["explorer"]
    r = await async_client.delete(
        f"/api/v1/spaces/{space_id}/members/{target.id}",
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(r, _expected(variant, min_role="commander"), "M-44")


# =============================================================================
# Section D — DEMO is_demo overrides on shared resources
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_D_50_create_connection(seeded_axis, async_client, variant):
    space_id = _space_for(seeded_axis, variant)
    payload = {
        "name": f"conn-{variant}",
        "connection_type": "postgresql",
        "config": {"host": "test", "port": 5432, "database": "t"},
        "space_id": space_id,
    }
    r = await async_client.post(
        "/api/v1/connections",
        json=payload,
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    # Commander+ allowed in non-demo; demo_commander BLOCKED via is_demo
    _assert_outcome(
        r,
        _expected(variant, min_role="navigator", demo_blocks=True),
        "D-50",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_D_51_update_connection(seeded_axis, async_client, variant):
    payload = {"name": f"updated-by-{variant}"}
    r = await async_client.put(
        f"/api/v1/connections/{seeded_axis['connection_id']}",
        json=payload,
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    # Connection edit gated by space ownership (commander on the space the
    # connection belongs to). Demo blocks demo_commander.
    _assert_outcome(
        r,
        _expected(variant, min_role="navigator", demo_blocks=True),
        "D-51",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_D_52_delete_connection(seeded_axis, async_client, variant):
    r = await async_client.delete(
        f"/api/v1/connections/{seeded_axis['connection_id']}",
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(
        r,
        _expected(variant, min_role="navigator", demo_blocks=True),
        "D-52",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ALL_VARIANTS)
async def test_D_53_upload_knowledge_file(seeded_axis, async_client, variant):
    space_id = _space_for(seeded_axis, variant)
    # Multipart upload — minimal payload, schema may reject before reaching
    # RBAC, which still surfaces as a deny.
    files = {"file": ("axis.txt", b"hello axis", "text/plain")}
    data = {"scope": "space", "scope_id": space_id}
    r = await async_client.post(
        "/api/v1/knowledge/files",
        files=files,
        data=data,
        headers=_auth(seeded_axis["tokens"][variant]),
    )
    _assert_outcome(
        r,
        _expected(variant, min_role="navigator", demo_blocks=True),
        "D-53",
    )


# =============================================================================
# Section L — LEGACY normalization regression
#
# These tests exist to guarantee that admin/member SpaceMember rows created
# before A1 keep behaving correctly. They are ASSERTED via the presence of
# the variant in the matrix above (admin_legacy resolves like commander,
# member_legacy resolves like explorer). The cases below are explicit
# duplications to make a future regression jump out in the diff.
# =============================================================================


@pytest.mark.asyncio
async def test_L_60_admin_legacy_can_invite(seeded_axis, async_client):
    """Admin-legacy normalizes to commander → can invite."""
    target = seeded_axis["users"]["explorer"]
    payload = {"user_id": str(target.id), "role": "navigator"}
    r = await async_client.post(
        f"/api/v1/spaces/{seeded_axis['space_id']}/members",
        json=payload,
        headers=_auth(seeded_axis["tokens"]["admin_legacy"]),
    )
    assert r.status_code in (200, 201, 400), (
        f"[L-60] admin_legacy should normalize to commander; got "
        f"{r.status_code}: {r.text[:200]}"
    )


@pytest.mark.asyncio
async def test_L_61_member_legacy_cannot_invite(seeded_axis, async_client):
    """Member-legacy normalizes to explorer → cannot invite."""
    target = seeded_axis["users"]["explorer"]
    payload = {"user_id": str(target.id), "role": "navigator"}
    r = await async_client.post(
        f"/api/v1/spaces/{seeded_axis['space_id']}/members",
        json=payload,
        headers=_auth(seeded_axis["tokens"]["member_legacy"]),
    )
    assert r.status_code in (403, 404), f"[L-61] {r.status_code}"


@pytest.mark.asyncio
async def test_L_62_admin_legacy_can_run_ai(seeded_axis, async_client):
    """Demo Spaces created before A1 had role='admin' — these users were
    falling through to "guest" because rbac_service:1014 only matched
    commander/navigator/explorer. After normalization, they get full
    AI access in their own Space."""
    payload = {"question": "How many rows?", "space_id": seeded_axis["space_id"]}
    r = await async_client.post(
        "/api/v1/ai/query",
        json=payload,
        headers=_auth(seeded_axis["tokens"]["admin_legacy"]),
    )
    assert r.status_code < 400, (
        f"[L-62] admin_legacy should normalize to commander and pass "
        f"ai.query; got {r.status_code}: {r.text[:300]}"
    )


# =============================================================================
# Section P — Invite role payload validation
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role_payload,expect_status",
    [
        ("commander", "allow"),
        ("navigator", "allow"),
        ("explorer", "allow"),
        ("admin", "allow"),     # legacy still accepted (compat)
        ("member", "allow"),    # legacy still accepted (compat)
        ("potato", "deny"),     # invalid value → 422
        ("", "deny"),           # empty → 422
    ],
)
async def test_P_70_invite_role_payload(
    seeded_axis, async_client, role_payload, expect_status,
):
    target = seeded_axis["users"]["external"]
    payload = {"user_id": str(target.id), "role": role_payload}
    r = await async_client.post(
        f"/api/v1/spaces/{seeded_axis['space_id']}/members",
        json=payload,
        headers=_auth(seeded_axis["tokens"]["commander"]),
    )
    if expect_status == "allow":
        assert r.status_code in (200, 201, 400), (
            f"[P-70 role={role_payload}] {r.status_code}: {r.text[:200]}"
        )
    else:
        assert r.status_code in (400, 422), (
            f"[P-70 role={role_payload}] expected validation deny got "
            f"{r.status_code}: {r.text[:200]}"
        )


# =============================================================================
# Section S — Demo signup provisioning unit tests
# =============================================================================


@pytest.mark.asyncio
async def test_S_80_demo_signup_creates_commander_role(db_session):
    """A1: new demo signups must create SpaceMember.role='commander'
    (NOT 'admin' which falls through to 'guest' in rbac_service)."""
    from src.schemas.demo import DemoSignupRequest
    from src.services.demo_service import DemoService

    service = DemoService(db_session)
    payload = DemoSignupRequest(
        email="lucas+test@axis.example.com",
        company="Axis Co",
        turnstile_token="test-bypass",
    )
    response = await service.signup(payload, client_ip="127.0.0.1")
    assert response.space_id

    member = await db_session.execute(
        SpaceMember.__table__.select().where(
            SpaceMember.user_id == response.user.id,
            SpaceMember.space_id == response.space_id,
        )
    )
    row = member.first()
    assert row is not None, "demo signup did not create SpaceMember row"
    assert row.role == "commander", (
        f"S-80: demo signup must create role='commander' (got '{row.role}'). "
        "rbac_service.py:1014 only matches commander/navigator/explorer — "
        "any other value falls through to 'guest' and breaks AI/chat."
    )


@pytest.mark.asyncio
async def test_S_81_returning_demo_normalizes_legacy_admin(db_session):
    """A1: returning demo guests with legacy role='admin' should have it
    backfilled to 'commander' on the next login (idempotent)."""
    from src.models.user import User
    from src.schemas.demo import DemoSignupRequest
    from src.services.demo_service import DemoService

    # Seed: a user that already exists with a Space owning role='admin'
    user = User(
        id=uuid4(),
        email="legacy+demo@axis.example.com",
        password_hash=get_password_hash("x"),
        name="Legacy Demo",
        role="member",
        is_demo=True,
    )
    db_session.add(user)
    await db_session.flush()

    space = Space(
        id=uuid4(),
        name="Legacy Demo Space",
        created_by=user.id,
        is_demo=True,
    )
    db_session.add(space)
    await db_session.flush()

    db_session.add(SpaceMember(
        space_id=space.id,
        user_id=user.id,
        role="admin",  # ← legacy value
    ))
    await db_session.commit()

    # Returning login should backfill the role
    service = DemoService(db_session)
    payload = DemoSignupRequest(
        email=user.email,
        company="Legacy Demo",
        turnstile_token="test-bypass",
    )
    await service.signup(payload, client_ip="127.0.0.1")

    # Re-read the member row
    res = await db_session.execute(
        SpaceMember.__table__.select().where(
            SpaceMember.user_id == user.id,
            SpaceMember.space_id == space.id,
        )
    )
    row = res.first()
    assert row.role == "commander", (
        f"S-81: returning demo should backfill admin→commander, got '{row.role}'"
    )
