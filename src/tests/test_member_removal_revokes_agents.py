"""Wire-in tests for W12 — verify space/crew member removal invokes
``AgentRevocationService``. Black-box: seed data, call the service
method, assert the agent is paused.
"""

from __future__ import annotations

import uuid

import pytest

from src.models.agent import Agent, AgentScope, AgentStatus
from src.models.crew import Crew, CrewMember
from src.models.space import Space, SpaceMember
from src.models.user import User
from src.services.crew_service import CrewService
from src.services.space_service import SpaceService


def _user(role: str = "admin") -> User:
    return User(
        id=uuid.uuid4(),
        email=f"u-{uuid.uuid4().hex[:6]}@x.test",
        name="t",
        password_hash="x",
        role=role,
    )


def _agent_in_space(*, creator: uuid.UUID, space: uuid.UUID) -> Agent:
    return Agent(
        id=uuid.uuid4(),
        name="a",
        archetype="custom",
        scope=AgentScope.SPACE.value,
        scope_id=str(space),
        status=AgentStatus.ACTIVE.value,
        monitor_type="question",
        focus="t",
        frequency="daily",
        connection_ids=[],
        created_by=creator,
        identity_type="user",
    )


def _agent_in_crew(*, creator: uuid.UUID, crew: uuid.UUID) -> Agent:
    return Agent(
        id=uuid.uuid4(),
        name="a",
        archetype="custom",
        scope=AgentScope.CREW.value,
        scope_id=str(crew),
        status=AgentStatus.ACTIVE.value,
        monitor_type="question",
        focus="t",
        frequency="daily",
        connection_ids=[],
        created_by=creator,
        identity_type="user",
    )


# ---------------------------------------------------------------------------
#  space removal → agent paused
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_space_member_pauses_creators_agents(db_session):
    admin = _user(role="admin")
    creator = _user(role="user")
    space_owner = _user(role="user")

    db_session.add_all([admin, creator, space_owner])
    await db_session.flush()

    space = Space(
        id=uuid.uuid4(),
        name="s",
        color="#FF0000",
        created_by=space_owner.id,
    )
    db_session.add(space)
    await db_session.flush()

    db_session.add(SpaceMember(space_id=space.id, user_id=creator.id, role="editor"))
    agent = _agent_in_space(creator=creator.id, space=space.id)
    db_session.add(agent)
    await db_session.commit()

    # Act — admin removes creator from space
    await SpaceService(db_session).remove_space_member(
        space_id=space.id,
        user_id=creator.id,
        current_user=admin,
    )

    # Re-fetch agent — must be paused
    await db_session.refresh(agent)
    assert agent.status == AgentStatus.PAUSED.value


@pytest.mark.asyncio
async def test_remove_space_member_does_not_pause_other_users_agents(db_session):
    admin = _user(role="admin")
    alice = _user(role="user")
    bob = _user(role="user")
    space_owner = _user(role="user")

    db_session.add_all([admin, alice, bob, space_owner])
    await db_session.flush()

    space = Space(
        id=uuid.uuid4(), name="s", color="#FF0000",
        created_by=space_owner.id,
    )
    db_session.add(space)
    await db_session.flush()

    db_session.add_all([
        SpaceMember(space_id=space.id, user_id=alice.id, role="editor"),
        SpaceMember(space_id=space.id, user_id=bob.id, role="editor"),
    ])
    bob_agent = _agent_in_space(creator=bob.id, space=space.id)
    db_session.add(bob_agent)
    await db_session.commit()

    # Remove alice — bob's agent must NOT be touched
    await SpaceService(db_session).remove_space_member(
        space_id=space.id,
        user_id=alice.id,
        current_user=admin,
    )

    await db_session.refresh(bob_agent)
    assert bob_agent.status == AgentStatus.ACTIVE.value


# ---------------------------------------------------------------------------
#  crew removal → agent paused
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_crew_member_pauses_creators_crew_agents(db_session):
    admin = _user(role="admin")
    creator = _user(role="user")
    space_owner = _user(role="user")

    db_session.add_all([admin, creator, space_owner])
    await db_session.flush()

    space = Space(
        id=uuid.uuid4(), name="s", color="#FF0000",
        created_by=space_owner.id,
    )
    db_session.add(space)
    await db_session.flush()

    crew = Crew(
        id=uuid.uuid4(),
        name="c",
        space_id=space.id,
        created_by=admin.id,
    )
    db_session.add(crew)
    db_session.add(SpaceMember(space_id=space.id, user_id=admin.id, role="owner"))
    db_session.add(SpaceMember(space_id=space.id, user_id=creator.id, role="editor"))
    await db_session.flush()

    db_session.add(CrewMember(crew_id=crew.id, user_id=creator.id, role="viewer"))
    agent = _agent_in_crew(creator=creator.id, crew=crew.id)
    db_session.add(agent)
    await db_session.commit()

    # Act — admin removes creator from crew
    await CrewService(db_session).remove_crew_member(
        crew_id=crew.id,
        user_id=creator.id,
        current_user=admin,
    )

    await db_session.refresh(agent)
    assert agent.status == AgentStatus.PAUSED.value
