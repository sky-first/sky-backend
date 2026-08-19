"""Tests for Phase 2.5 — Crew as first-class citizen in the resolver.

Modelling rules (Space = department, Crew = team within a department):

  • Crew membership inside a Space confers VISIBILITY only — viewer-
    level read access, so the user can navigate into the Space to
    reach their Crew. It does NOT escalate Space-level write/admin
    permissions.
  • Crew Owner manages Crew-scoped actions, NOT Space-scoped ones.
    A "Finance > Audit" Crew Owner cannot delete a Space-level page
    like "Company Finance 2026". The Space Owner can.
  • When a `crew_id` is passed explicitly, that Crew's role is what
    governs the active context. The resolver does NOT scan other
    Crews of the user inside the same Space looking for a higher
    role — that would let an Audit Crew Viewer impersonate an Audit
    Crew Owner because the user happens to also be Owner of an
    unrelated "Payroll" Crew.
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
async def test_crew_member_can_read_space_via_visibility(db_session):
    """Crew member with no SpaceMember row should be able to *view* the
    Space (visibility), so they can navigate into their Crew."""
    owner = await _user(db_session, role="admin", name="O")
    user = await _user(db_session, role="member", name="U")
    space = await _space(db_session, owner)
    crew = await _crew(db_session, owner, space)
    db_session.add(CrewMember(crew_id=crew.id, user_id=user.id, role="editor"))
    await db_session.commit()
    # connections.view (viewer-level) is granted via Crew → visibility.
    assert (
        await Authorization(db_session).can(
            user, "connections.view", space_id=space.id
        )
        is True
    )


@pytest.mark.asyncio
async def test_crew_editor_cannot_write_at_space_scope_without_crew_id(db_session):
    """A Crew editor with no SpaceMember row cannot perform a write
    action at Space scope when no crew_id is in the request — the
    resource isn't tied to their Crew, so their Crew membership must
    not escalate beyond visibility."""
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
        is False
    )


@pytest.mark.asyncio
async def test_crew_editor_can_write_when_crew_id_passed(db_session):
    """Same Crew editor — when the action is tied to the Crew via
    crew_id, the Crew's role IS authoritative and editor passes."""
    owner = await _user(db_session, role="admin", name="O")
    user = await _user(db_session, role="member", name="U")
    space = await _space(db_session, owner)
    crew = await _crew(db_session, owner, space)
    db_session.add(CrewMember(crew_id=crew.id, user_id=user.id, role="editor"))
    await db_session.commit()
    assert (
        await Authorization(db_session).can(
            # `agents.create` e não `connections.create`: estes testes são
            # sobre a **resolução do papel de crew**, e a chave era só o
            # veículo. `connections.create` passou a exigir dono do projeto —
            # ligar dados é a fronteira que o pedido de acesso guarda — por
            # isso deixou de servir para testar o nível de editor.
            user, "agents.create", space_id=space.id, crew_id=crew.id
        )
        is True
    )


@pytest.mark.asyncio
async def test_crew_owner_does_not_get_space_owner_powers(db_session):
    """Crew Owner with no SpaceMember row must NOT be able to perform
    Space-level admin actions (the user manages their Crew, not the
    whole Space). A Space-level page delete with no crew_id is denied."""
    owner = await _user(db_session, role="admin", name="O")
    user = await _user(db_session, role="member", name="U")
    space = await _space(db_session, owner)
    crew = await _crew(db_session, owner, space)
    db_session.add(CrewMember(crew_id=crew.id, user_id=user.id, role="owner"))
    await db_session.commit()
    # Space-scoped delete (no crew_id) — Crew Owner is NOT Space Owner.
    assert (
        await Authorization(db_session).can(
            user, "pages.delete", space_id=space.id
        )
        is False
    )
    # spaces.members.manage is Space-only — Crew Owner cannot manage
    # the Space's membership list either.
    assert (
        await Authorization(db_session).can(
            user, "spaces.members.manage", space_id=space.id
        )
        is False
    )


@pytest.mark.asyncio
async def test_crew_owner_can_act_within_their_own_crew(db_session):
    """Crew Owner CAN perform owner-level actions when the request is
    scoped to their Crew via crew_id — that's the whole point of the
    role. A Crew-scoped page delete is allowed."""
    owner = await _user(db_session, role="admin", name="O")
    user = await _user(db_session, role="member", name="U")
    space = await _space(db_session, owner)
    crew = await _crew(db_session, owner, space)
    db_session.add(CrewMember(crew_id=crew.id, user_id=user.id, role="owner"))
    await db_session.commit()
    assert (
        await Authorization(db_session).can(
            user, "pages.delete", space_id=space.id, crew_id=crew.id
        )
        is True
    )


@pytest.mark.asyncio
async def test_space_viewer_with_crew_owner_acts_as_owner_in_crew(db_session):
    """Space-viewer + Crew-owner: when crew_id is passed, the Crew role
    wins and the user can perform owner-level actions on Crew-scoped
    resources. Space-level resources still see them as a viewer."""
    owner = await _user(db_session, role="admin", name="O")
    user = await _user(db_session, role="member", name="U")
    space = await _space(db_session, owner)
    crew = await _crew(db_session, owner, space)
    db_session.add(SpaceMember(space_id=space.id, user_id=user.id, role="viewer"))
    db_session.add(CrewMember(crew_id=crew.id, user_id=user.id, role="owner"))
    await db_session.commit()
    # Crew-scoped page delete — allowed via Crew owner role.
    assert (
        await Authorization(db_session).can(
            user, "pages.delete", space_id=space.id, crew_id=crew.id
        )
        is True
    )
    # Space-scoped page delete (no crew_id) — denied: SpaceMember is
    # only viewer; Crew owner does NOT escalate to Space owner.
    assert (
        await Authorization(db_session).can(
            user, "pages.delete", space_id=space.id
        )
        is False
    )


@pytest.mark.asyncio
async def test_owning_one_crew_does_not_grant_owner_in_another(db_session):
    """User is Owner of Crew A and Viewer of Crew B in the same Space.
    Acting in Crew B context, they are a Viewer — NOT an Owner. The
    resolver must not pick the highest crew role across the Space when
    a specific crew_id was passed."""
    owner = await _user(db_session, role="admin", name="O")
    user = await _user(db_session, role="member", name="U")
    space = await _space(db_session, owner)
    crew_a = await _crew(db_session, owner, space, "A")
    crew_b = await _crew(db_session, owner, space, "B")
    db_session.add(CrewMember(crew_id=crew_a.id, user_id=user.id, role="owner"))
    db_session.add(CrewMember(crew_id=crew_b.id, user_id=user.id, role="viewer"))
    await db_session.commit()
    # Acting in Crew B (viewer): cannot delete a Crew B page.
    assert (
        await Authorization(db_session).can(
            user, "pages.delete", space_id=space.id, crew_id=crew_b.id
        )
        is False
    )
    # Acting in Crew A (owner): can delete a Crew A page.
    assert (
        await Authorization(db_session).can(
            user, "pages.delete", space_id=space.id, crew_id=crew_a.id
        )
        is True
    )


@pytest.mark.asyncio
async def test_crew_viewer_cannot_perform_editor_action_in_their_crew(db_session):
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
            user, "agents.create", crew_id=crew.id
        )
        is True
    )
