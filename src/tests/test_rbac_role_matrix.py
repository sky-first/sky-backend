"""RBAC role matrix — incremental coverage per role.

See docs/rbac-role-test-matrix.md for the full 150-case matrix.

Harness:
  - seed_tenant() builds ONE tenant + space + crew + connection + agent
    + dashboard + page + members (one user per role).
  - Each test is parameterized over (case_id, role, expected_status).
  - Expected status is either "allow" (2xx/204) or "deny" (403 or 404).

Run only this file:
    pytest src/tests/test_rbac_role_matrix.py -v

Run one section:
    pytest src/tests/test_rbac_role_matrix.py -v -k section_i
"""

from __future__ import annotations

from typing import Literal

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

# Phase 7 vocabulary. The Space-axis roles are viewer/editor/owner; the
# last two entries are platform-axis sentinels — `platform_admin`
# (user.role == "admin") and `tenant_owner` (user.role == "owner") have
# universal access regardless of their Space membership.
ROLES = ["viewer", "editor", "owner", "platform_admin", "tenant_owner"]
ROLE_IDX = {r: i for i, r in enumerate(ROLES)}


Expect = Literal["allow", "deny"]


def _expect_for_role(allowed_from: str, role: str) -> Expect:
    """Return allow/deny for a role given the minimum role that allows.

    `allowed_from` is the lowest role in ROLES that may perform the
    action. Any role at or above it in the ROLES list is allowed;
    anyone below is denied.
    """
    return "allow" if ROLE_IDX[role] >= ROLE_IDX[allowed_from] else "deny"


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _assert_outcome(resp, expected: Expect, case_id: str) -> None:
    if expected == "allow":
        assert resp.status_code < 400, (
            f"[{case_id}] expected allow but got {resp.status_code}: {resp.text[:200]}"
        )
    else:
        assert resp.status_code in (403, 404), (
            f"[{case_id}] expected deny (403/404) but got {resp.status_code}: {resp.text[:200]}"
        )


# -----------------------------------------------------------------------------
# Seed fixture — one tenant populated with a user per role
# -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded(db_session) -> dict:
    """Seed a tenant with one user per role + shared resources.

    Returns a dict with tokens keyed by role name.
    """
    from src.core.security import create_access_token, get_password_hash
    from src.models.agent import Agent
    from src.models.space import Space, SpaceMember
    from src.repositories.user import UserRepository

    user_repo = UserRepository(db_session)
    users: dict[str, object] = {}
    tokens: dict[str, str] = {}

    for role in ROLES:
        # Map the test-fixture label to the user.role column. `tenant_owner`
        # gets user.role="owner" (the platform-axis tenant founder); the
        # Space-axis "owner" entry stays a member at the platform level
        # and gains its privileges through the SpaceMember row.
        platform_role = (
            "owner" if role == "tenant_owner"
            else "admin" if role == "platform_admin"
            else "member"
        )
        u = await user_repo.create(
            email=f"{role}@rbac-test.example.com",
            password_hash=get_password_hash("test"),
            name=role.title(),
            role=platform_role,
        )
        users[role] = u
        tokens[role] = create_access_token({
            "sub": str(u.id),
            "email": u.email,
            "role": platform_role,
        })

    space_owner = users["owner"]
    space = Space(name="RBAC Test Space", created_by=space_owner.id)
    db_session.add(space)
    await db_session.flush()

    for r in ("owner", "editor", "viewer"):
        db_session.add(SpaceMember(
            space_id=space.id,
            user_id=users[r].id,
            role=r,
        ))

    agent = Agent(
        name="RBAC test agent",
        archetype="custom",
        scope="space",
        scope_id=str(space.id),
        status="active",
        monitor_type="question",
        focus="What is happening?",
        frequency="daily",
        connection_ids=[],
        created_by=space_owner.id,
    )
    db_session.add(agent)
    await db_session.commit()

    return {
        "users": users,
        "tokens": tokens,
        "space_id": str(space.id),
        "agent_id": str(agent.id),
    }


# -----------------------------------------------------------------------------
# Section I — Read surfaces (baseline Explorer)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_section_i_01_list_spaces(seeded, async_client, role):
    r = await async_client.get("/api/v1/spaces", headers=_auth_headers(seeded["tokens"][role]))
    _assert_outcome(r, _expect_for_role("viewer", role), "I-01")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_section_i_02_get_space_detail(seeded, async_client, role):
    r = await async_client.get(f"/api/v1/spaces/{seeded['space_id']}", headers=_auth_headers(seeded["tokens"][role]))
    _assert_outcome(r, _expect_for_role("viewer", role), "I-02")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_section_i_03_list_space_members(seeded, async_client, role):
    r = await async_client.get(f"/api/v1/spaces/{seeded['space_id']}/members", headers=_auth_headers(seeded["tokens"][role]))
    _assert_outcome(r, _expect_for_role("viewer", role), "I-03")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_section_i_08_list_agents(seeded, async_client, role):
    r = await async_client.get("/api/v1/agents/", headers=_auth_headers(seeded["tokens"][role]))
    _assert_outcome(r, _expect_for_role("viewer", role), "I-08")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_section_i_09_get_agent(seeded, async_client, role):
    r = await async_client.get(f"/api/v1/agents/{seeded['agent_id']}", headers=_auth_headers(seeded["tokens"][role]))
    _assert_outcome(r, _expect_for_role("viewer", role), "I-09")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_section_i_10_list_findings(seeded, async_client, role):
    r = await async_client.get(f"/api/v1/agents/{seeded['agent_id']}/findings", headers=_auth_headers(seeded["tokens"][role]))
    _assert_outcome(r, _expect_for_role("viewer", role), "I-10")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_section_i_12_agent_metrics(seeded, async_client, role):
    r = await async_client.get(f"/api/v1/agents/{seeded['agent_id']}/metrics", headers=_auth_headers(seeded["tokens"][role]))
    _assert_outcome(r, _expect_for_role("viewer", role), "I-12")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_section_i_24_me(seeded, async_client, role):
    r = await async_client.get("/api/v1/users/me", headers=_auth_headers(seeded["tokens"][role]))
    _assert_outcome(r, _expect_for_role("viewer", role), "I-24")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_section_i_30_audit_logs(seeded, async_client, role):
    r = await async_client.get("/api/v1/audit/events", headers=_auth_headers(seeded["tokens"][role]))
    _assert_outcome(r, _expect_for_role("platform_admin", role), "I-30")


# -----------------------------------------------------------------------------
# Section II — Write (baseline Navigator)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_section_ii_31_create_agent(seeded, async_client, role):
    payload = {
        "name": f"agent-{role}",
        "archetype": "custom",
        "scope": "space",
        "scope_id": seeded["space_id"],
        "monitor_type": "question",
        "focus": "test",
        "frequency": "daily",
        "connection_ids": [],
    }
    r = await async_client.post("/api/v1/agents/", json=payload, headers=_auth_headers(seeded["tokens"][role]))
    _assert_outcome(r, _expect_for_role("editor", role), "II-31")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_section_ii_34_pause_agent(seeded, async_client, role):
    r = await async_client.post(f"/api/v1/agents/{seeded['agent_id']}/pause", headers=_auth_headers(seeded["tokens"][role]))
    _assert_outcome(r, _expect_for_role("editor", role), "II-34")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_section_ii_36_update_agent(seeded, async_client, role):
    r = await async_client.put(
        f"/api/v1/agents/{seeded['agent_id']}",
        json={"name": f"updated-by-{role}"},
        headers=_auth_headers(seeded["tokens"][role]),
    )
    _assert_outcome(r, _expect_for_role("editor", role), "II-36")


# -----------------------------------------------------------------------------
# Section III — Manage (baseline Commander)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_section_iii_61_add_space_member(seeded, async_client, role):
    target = seeded["users"]["viewer"]
    payload = {"user_id": str(target.id), "role": "editor"}
    r = await async_client.post(
        f"/api/v1/spaces/{seeded['space_id']}/members",
        json=payload,
        headers=_auth_headers(seeded["tokens"][role]),
    )
    expected = _expect_for_role("owner", role)
    if expected == "allow":
        assert r.status_code in (200, 201, 400), f"[III-61] {r.status_code}: {r.text[:200]}"
    else:
        assert r.status_code == 403, f"[III-61] expected 403 got {r.status_code}"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_section_iii_64_create_crew(seeded, async_client, role):
    payload = {"name": f"crew-{role}", "space_id": seeded["space_id"]}
    r = await async_client.post("/api/v1/crews", json=payload, headers=_auth_headers(seeded["tokens"][role]))
    # crews.create is a tenant-level "any_member" rule in PERMISSION_RULES,
    # so anyone with a valid platform role can create a crew (they become
    # its owner). The per-Space role is irrelevant for the creation call.
    _assert_outcome(r, _expect_for_role("viewer", role), "III-64")


# -----------------------------------------------------------------------------
# Section IV — Platform ops (baseline Admin)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_section_iv_91_create_space(seeded, async_client, role):
    payload = {"name": f"space-{role}", "description": "rbac test"}
    r = await async_client.post("/api/v1/spaces", json=payload, headers=_auth_headers(seeded["tokens"][role]))
    # spaces.create is now ("tenant", "admin_or_above"). Platform
    # Members can no longer spin up new Spaces because each one
    # carries its own RBAC scope, service principal and knowledge
    # footprint — uncontrolled fan-out becomes ungoverned silos.
    # Demo signup bypasses this rule via DemoService (system action),
    # not the API gate.
    _assert_outcome(r, _expect_for_role("platform_admin", role), "IV-91")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_section_iv_96_list_users(seeded, async_client, role):
    r = await async_client.get("/api/v1/users", headers=_auth_headers(seeded["tokens"][role]))
    _assert_outcome(r, _expect_for_role("platform_admin", role), "IV-96")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_section_iv_99_agents_summary(seeded, async_client, role):
    r = await async_client.get("/api/v1/agents/metrics/summary", headers=_auth_headers(seeded["tokens"][role]))
    # The summary endpoint gates on `metrics.view` (space, viewer). When
    # called without a space_id the resolver falls back to the user's
    # best-role-anywhere, so any user with at least viewer membership in
    # any Space sees the tenant rollup.
    _assert_outcome(r, _expect_for_role("viewer", role), "IV-99")
