"""Pin the Personal-mode space_ids resolver wired into AIService.

Without this helper, a member of S1 asking the AI in Personal mode
would only see (a) their own user-id-scoped embeddings + (b) shared
NULL-keyed rows. The space-scoped rows that S1's admin indexed under
S1.id would be hidden — Personal would be a strict subset of S1's
collaborative answers.

Companion to AI PR #175 which added `caller_space_ids` to
`_build_embedding_base_query`. This test covers the BE side
(`AIService._get_user_space_ids`).
"""

from __future__ import annotations

import uuid

import pytest

from src.models.space import Space, SpaceMember
from src.models.user import User
from src.services.ai_service import AIService


async def _make_user(db_session, label: str) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{label}.{uuid.uuid4().hex[:8]}@example.com",
        role="user",
        password_hash="dummy",
        name=f"{label} User",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.mark.asyncio
async def test_user_with_no_spaces_returns_empty_list(db_session):
    user = await _make_user(db_session, "lonely")
    service = AIService(db_session)
    spaces = await service._get_user_space_ids(user.id)
    assert spaces == []


@pytest.mark.asyncio
async def test_user_owned_space_is_returned(db_session):
    user = await _make_user(db_session, "owner")
    s = Space(id=uuid.uuid4(), name="Owned", created_by=user.id)
    db_session.add(s)
    await db_session.flush()

    service = AIService(db_session)
    spaces = await service._get_user_space_ids(user.id)
    assert str(s.id) in spaces
    assert len(spaces) == 1


@pytest.mark.asyncio
async def test_member_space_is_returned(db_session):
    owner = await _make_user(db_session, "ownr")
    member = await _make_user(db_session, "mbr")
    s = Space(id=uuid.uuid4(), name="Shared", created_by=owner.id)
    db_session.add(s)
    await db_session.flush()
    db_session.add(SpaceMember(id=uuid.uuid4(), space_id=s.id, user_id=member.id, role="editor"))
    await db_session.flush()

    service = AIService(db_session)
    member_spaces = await service._get_user_space_ids(member.id)
    assert str(s.id) in member_spaces


@pytest.mark.asyncio
async def test_owner_and_member_spaces_are_unique(db_session):
    user = await _make_user(db_session, "both")
    s_owned = Space(id=uuid.uuid4(), name="Owned", created_by=user.id)
    other_owner = await _make_user(db_session, "other")
    s_member = Space(id=uuid.uuid4(), name="Member", created_by=other_owner.id)
    db_session.add_all([s_owned, s_member])
    await db_session.flush()
    db_session.add(SpaceMember(id=uuid.uuid4(), space_id=s_member.id, user_id=user.id, role="member"))
    await db_session.flush()

    service = AIService(db_session)
    spaces = await service._get_user_space_ids(user.id)
    assert sorted(spaces) == sorted([str(s_owned.id), str(s_member.id)])


@pytest.mark.asyncio
async def test_other_users_spaces_are_not_leaked(db_session):
    """Cross-tenant isolation: caller A must not see Space owned by
    or membered by user B if A has no relationship to it. This is
    the contract that makes the AI #175 OR-clause safe."""
    a = await _make_user(db_session, "alice")
    b = await _make_user(db_session, "bob")
    s_b = Space(id=uuid.uuid4(), name="Bob's Space", created_by=b.id)
    db_session.add(s_b)
    await db_session.flush()

    service = AIService(db_session)
    a_spaces = await service._get_user_space_ids(a.id)
    assert str(s_b.id) not in a_spaces
