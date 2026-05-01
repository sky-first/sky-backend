"""Tests for Phase 2.5 — Crew as first-class citizen in the resolver.

Coverage:
  • Crew membership alone (no Space membership) grants access at the
    Crew's role level
  • Member of N Crews in the same Space — highest Crew role wins
  • Resource gated on space_id with a member that's only in a Crew
    inside that Space — best_crew_in_space lookup grants access
  • Crew member at editor level can perform editor actions; viewer
    in same Crew cannot
  • Space-level viewer + Crew-level owner: effective is owner (Crew
    membership escalates over Space)
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import get_password_hash
from src.models.crew import Crew, CrewMember
from src.models.space import Space, SpaceMember
from src.models.user import User
from src.repositories.user import UserRepository
from src.services.authorization import Authorization


async def _user(db: AsyncSession, *, role: str, name: str) -> User:
    return await UserRepository(db).create(
        email=f"{uuid4().hex[:8]}@example.com",
        password_hash=get_password_hash("Test@2024!"),
        name=name,
        role=role,
    )


async def _space(db: AsyncSession, owner: User, name: str = "S") -> Space:
    s = Space(name=f"{name} {uuid4().hex[:6]}", created_by=owner.id)
    db.add(s)
    await db.flush()
    return s


async def _crew(db: AsyncSession, owner: User, space: Space, name: str = "C") -> Crew:
    c = Crew(
        name=f"{name} {uuid4().hex[:6]}",
        space_id=space.id,
        created_by=owner.id,
    )
    db.add(c)
    await db.flush()
    return c


@pytest.mark.asyncio
async def test_crew_membership_alone_grants_access(db_session):
    """User has NO SpaceMember row but is a Crew member at editor level.
    Action `connections.create` (editor) on the Space should be allowed
    via best_crew_in_space."""
    owner = await _user(db_session, role="admin", name="O")
    user = await _user(db_session, role="member", name="U")
    space = await _space(db_session, owner)
    crew = await _crew(db_session, owner, space)
    db_session.add(CrewMember(crew_id=crew.id, user_id=user.id, role="editor"))
    await db_session.commit()
    assert (
        await Authorization(db_session).can(
            user, "connections.create", space_id=space.id
        )
        is True
    )


@pytest.mark.asyncio
async def test_member_of_two_crews_takes_highest_role(db_session):
    owner = await _user(db_session, role="admin", name="O")
    user = await _user(db_session, role="member", name="U")
    space = await _space(db_session, owner)
    crew_a = await _crew(db_session, owner, space, "A")
    crew_b = await _crew(db_session, owner, space, "B")
    db_session.add(CrewMember(crew_id=crew_a.id, user_id=user.id, role="viewer"))
    db_session.add(CrewMember(crew_id=crew_b.id, user_id=user.id, role="owner"))
    await db_session.commit()
    # Owner-level Crew membership grants spaces.members.manage (Space owner)
    assert (
        await Authorization(db_session).can(
            user, "spaces.members.manage", space_id=space.id
        )
        is True
    )


@pytest.mark.asyncio
async def test_crew_owner_escalates_over_space_viewer(db_session):
    owner = await _user(db_session, role="admin", name="O")
    user = await _user(db_session, role="member", name="U")
    space = await _space(db_session, owner)
    crew = await _crew(db_session, owner, space)
    db_session.add(SpaceMember(space_id=space.id, user_id=user.id, role="viewer"))
    db_session.add(CrewMember(crew_id=crew.id, user_id=user.id, role="owner"))
    await db_session.commit()
    # Even though Space membership is viewer, the Crew-owner role escalates
    # the effective level to owner — pages.delete (owner-only) is allowed.
    assert (
        await Authorization(db_session).can(
            user, "pages.delete", space_id=space.id, crew_id=crew.id
        )
        is True
    )


@pytest.mark.asyncio
async def test_crew_viewer_cannot_perform_editor_action(db_session):
    owner = await _user(db_session, role="admin", name="O")
    user = await _user(db_session, role="member", name="U")
    space = await _space(db_session, owner)
    crew = await _crew(db_session, owner, space)
    db_session.add(CrewMember(crew_id=crew.id, user_id=user.id, role="viewer"))
    await db_session.commit()
    assert (
        await Authorization(db_session).can(
            user, "connections.create", space_id=space.id, crew_id=crew.id
        )
        is False
    )


@pytest.mark.asyncio
async def test_crew_id_alone_resolves_when_space_id_omitted(db_session):
    owner = await _user(db_session, role="admin", name="O")
    user = await _user(db_session, role="member", name="U")
    space = await _space(db_session, owner)
    crew = await _crew(db_session, owner, space)
    db_session.add(CrewMember(crew_id=crew.id, user_id=user.id, role="editor"))
    await db_session.commit()
    assert (
        await Authorization(db_session).can(
            user, "connections.create", crew_id=crew.id
        )
        is True
    )


@pytest.mark.asyncio
async def test_crew_owner_escalates_when_only_space_id_passed(db_session):
    """Regression test for Phase 2.5 footgun: the resolver previously
    only consulted best_crew_in_space when the user had NO SpaceMember
    row. A user who is space-viewer + crew-owner must still surface
    owner UX when the caller passes only space_id (typical UI path
    where no crew is selected)."""
    owner = await _user(db_session, role="admin", name="O")
    user = await _user(db_session, role="member", name="U")
    space = await _space(db_session, owner)
    crew = await _crew(db_session, owner, space)
    db_session.add(SpaceMember(space_id=space.id, user_id=user.id, role="viewer"))
    db_session.add(CrewMember(crew_id=crew.id, user_id=user.id, role="owner"))
    await db_session.commit()
    # No crew_id passed — resolver must walk Crews under this Space and
    # discover the owner-level membership.
    assert (
        await Authorization(db_session).can(
            user, "pages.delete", space_id=space.id
        )
        is True
    )
