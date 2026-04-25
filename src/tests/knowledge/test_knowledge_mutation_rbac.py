"""Knowledge — mutation RBAC matrix.

Phase 3. Pins the 4-scope × N-role write rules from
KNOWLEDGE_REFACTOR.md §4 + §5.2 (MUT-01 through MUT-14).
"""

from __future__ import annotations

import pytest

PHASE = "Phase 3 — Mutation gates"


@pytest.mark.skip(reason=f"{PHASE} (MUT-01) — Personal scope is open to its owner")
@pytest.mark.asyncio
async def test_mut_01_any_user_writes_to_own_personal(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (MUT-02) — Personal of another user is denied")
@pytest.mark.asyncio
async def test_mut_02_user_cannot_write_to_other_users_personal(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (MUT-03) — Crew Commander allowed")
@pytest.mark.asyncio
async def test_mut_03_crew_commander_writes_to_own_crew(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (MUT-04) — Crew Navigator allowed")
@pytest.mark.asyncio
async def test_mut_04_crew_navigator_writes_to_own_crew(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (MUT-05) — Crew Explorer denied")
@pytest.mark.asyncio
async def test_mut_05_crew_explorer_denied(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (MUT-06) — sibling crew denied")
@pytest.mark.asyncio
async def test_mut_06_commander_cannot_write_to_sibling_crew(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (MUT-07) — Space Commander allowed")
@pytest.mark.asyncio
async def test_mut_07_space_commander_writes_to_own_space(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (MUT-08) — Space Navigator denied (different from Crew gate)")
@pytest.mark.asyncio
async def test_mut_08_space_navigator_denied(db_session):
    """Space scope is stricter than Crew scope on purpose — wider blast
    radius. Navigators can co-edit inside their crew, but not at the
    space-wide level."""
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (MUT-09) — Org write by Owner")
@pytest.mark.asyncio
async def test_mut_09_owner_writes_to_org(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (MUT-10) — Admin without knowledge.certify is denied at Org")
@pytest.mark.asyncio
async def test_mut_10_admin_without_certify_perm_denied_at_org(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (MUT-11) — Admin WITH knowledge.certify is allowed")
@pytest.mark.asyncio
async def test_mut_11_admin_with_certify_perm_writes_to_org(db_session):
    """The headline delegation test. Owner can grant
    ``knowledge.certify`` to a specific admin (not all admins).
    That single admin then gets Org-write capability without
    becoming Owner."""
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (MUT-12) — Member denied at Org")
@pytest.mark.asyncio
async def test_mut_12_member_denied_at_org(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (MUT-13) — revoking certify removes access live")
@pytest.mark.asyncio
async def test_mut_13_revoke_knowledge_certify_blocks_admin(db_session):
    """Owner can revoke the grant; on next request the admin is
    denied. No cached permission state should keep them in."""
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (MUT-14) — same matrix applies to update + delete")
@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["update", "delete"])
async def test_mut_14_same_rules_apply_to_update_and_delete(db_session, action):
    raise NotImplementedError
