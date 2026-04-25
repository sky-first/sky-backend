"""Knowledge — visibility / ACL contract.

Phase 2. Pins the read-side rules from KNOWLEDGE_REFACTOR.md §5.1
(ACL-01 through ACL-10).

Every test starts ``skip``'d. As Phase 2 ships, remove the marker
one test at a time, watch it fail, then make it pass. When the
file has zero skips, Phase 2's ACL slice is delivered.
"""

from __future__ import annotations

import pytest

PHASE = "Phase 2 — Knowledge tables + ACL"


@pytest.mark.skip(reason=f"{PHASE} not yet implemented (ACL-01)")
@pytest.mark.asyncio
async def test_acl_01_owner_sees_their_personal_metric(db_session):
    """Personal scope is the user's sandbox — they always see their own."""
    raise NotImplementedError("KnowledgeService.list_metrics(user) not yet implemented")


@pytest.mark.skip(reason=f"{PHASE} (ACL-02) — cross-user isolation")
@pytest.mark.asyncio
async def test_acl_02_user_does_not_see_another_users_personal_metric(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (ACL-03)")
@pytest.mark.asyncio
async def test_acl_03_crew_member_sees_crew_metric(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (ACL-04) — sibling-crew isolation")
@pytest.mark.asyncio
async def test_acl_04_crew_member_does_not_see_sibling_crew_metric(db_session):
    """The headline RBAC test: Alice in C1, Bob in C2; both in S1.
    Alice MUST NOT see Bob's crew-scoped metric. Tested at the
    service level AND through the AI service's
    ``list_authorized_embedding_ids`` so the embedding ACL stays
    consistent with the entity ACL.
    """
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (ACL-05)")
@pytest.mark.asyncio
async def test_acl_05_crew_member_sees_parent_space_metric(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (ACL-06)")
@pytest.mark.asyncio
async def test_acl_06_user_in_one_space_does_not_see_other_space_metrics(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (ACL-07)")
@pytest.mark.asyncio
async def test_acl_07_all_authenticated_users_see_org_metrics(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (ACL-08) — multi-crew union")
@pytest.mark.asyncio
async def test_acl_08_multi_crew_user_sees_union_of_crews(db_session):
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (ACL-09) — embedding ACL parity")
@pytest.mark.asyncio
async def test_acl_09_ai_authorized_embedding_ids_matches_visible_set(db_session):
    """The embedding ACL service used by the AI retrieval path must
    match the entity-level visibility. Drift here means the chat
    answers leak data that the regular UI hides — exactly the W2
    gap red-team targeted."""
    raise NotImplementedError


@pytest.mark.skip(reason=f"{PHASE} (ACL-10) — soft-delete invisibility")
@pytest.mark.asyncio
async def test_acl_10_soft_deleted_metric_is_invisible(db_session):
    raise NotImplementedError
