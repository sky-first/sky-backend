"""Wire-in test: deleting a user pauses every agent they created.

Master plan §12 + W12 follow-up. Closes the third revocation entrypoint
(after space/crew member removal in PR #258).
"""

from __future__ import annotations

import uuid

import pytest

from src.models.agent import Agent, AgentScope, AgentStatus
from src.models.user import User
from src.services.user_service import UserService


def _user(role: str = "user") -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:6]}@x.test",
        name="t",
        password_hash="x",
        role=role,
    )


def _agent(*, creator: uuid.UUID, scope: AgentScope, scope_id: uuid.UUID) -> Agent:
    return Agent(
        id=uuid.uuid4(),
        name="a",
        archetype="custom",
        scope=scope.value,
        scope_id=str(scope_id),
        status=AgentStatus.ACTIVE.value,
        monitor_type="question",
        focus="t",
        frequency="daily",
        connection_ids=[],
        created_by=creator,
        identity_type="user",
    )


@pytest.mark.asyncio
async def test_delete_user_pauses_every_creator_agent(db_session):
    admin = _user(role="admin")
    target = _user(role="user")
    db_session.add_all([admin, target])
    await db_session.flush()

    space_agent = _agent(creator=target.id, scope=AgentScope.SPACE, scope_id=uuid.uuid4())
    crew_agent = _agent(creator=target.id, scope=AgentScope.CREW, scope_id=uuid.uuid4())
    personal_agent = _agent(
        creator=target.id, scope=AgentScope.PERSONAL, scope_id=target.id,
    )
    db_session.add_all([space_agent, crew_agent, personal_agent])
    await db_session.commit()

    await UserService(db_session).delete_user(user_id=target.id, current_user=admin)

    for ag in (space_agent, crew_agent, personal_agent):
        await db_session.refresh(ag)
        assert ag.status == AgentStatus.PAUSED.value, (
            f"{ag.scope} agent should be paused after creator deletion"
        )


@pytest.mark.asyncio
async def test_delete_user_does_not_pause_other_users_agents(db_session):
    admin = _user(role="admin")
    target = _user(role="user")
    bystander = _user(role="user")
    db_session.add_all([admin, target, bystander])
    await db_session.flush()

    target_agent = _agent(creator=target.id, scope=AgentScope.SPACE, scope_id=uuid.uuid4())
    bystander_agent = _agent(
        creator=bystander.id, scope=AgentScope.SPACE, scope_id=uuid.uuid4(),
    )
    db_session.add_all([target_agent, bystander_agent])
    await db_session.commit()

    await UserService(db_session).delete_user(user_id=target.id, current_user=admin)

    await db_session.refresh(bystander_agent)
    assert bystander_agent.status == AgentStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_delete_user_already_paused_agent_skipped(db_session):
    admin = _user(role="admin")
    target = _user(role="user")
    db_session.add_all([admin, target])
    await db_session.flush()

    paused = Agent(
        id=uuid.uuid4(),
        name="p",
        archetype="custom",
        scope=AgentScope.SPACE.value,
        scope_id=str(uuid.uuid4()),
        status=AgentStatus.PAUSED.value,  # already paused
        monitor_type="question",
        focus="t",
        frequency="daily",
        connection_ids=[],
        created_by=target.id,
        identity_type="user",
    )
    db_session.add(paused)
    await db_session.commit()

    # Should not crash; should leave paused as-is.
    await UserService(db_session).delete_user(user_id=target.id, current_user=admin)
    await db_session.refresh(paused)
    assert paused.status == AgentStatus.PAUSED.value


@pytest.mark.asyncio
async def test_delete_user_with_no_agents_still_succeeds(db_session):
    admin = _user(role="admin")
    target = _user(role="user")
    db_session.add_all([admin, target])
    await db_session.commit()

    # No agents seeded — primary action (delete user) must still complete.
    await UserService(db_session).delete_user(user_id=target.id, current_user=admin)
