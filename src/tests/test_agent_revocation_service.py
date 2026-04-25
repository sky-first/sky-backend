"""W12 — agent revocation tests.

Mirror of master plan §12 + HI-002 follow-up.

QA perspectives covered:
  - Creator removed from Space → Space-scoped agent paused.
  - Creator removed from Space → other-Space agent NOT paused.
  - Creator removed from Crew → Crew-scoped agent paused; Space-scoped
    agent untouched.
  - Personal agent never paused by space removal (ties to creator
    existence, not space membership).
  - User deactivated → every agent paused regardless of scope.
  - Org-scoped agent listing the removed space gets paused.
  - Periodic sweep finds orphans even without an event firing.
  - Already-paused agent stays paused (no double-write).
  - Service principal agent (created_by=None) NEVER paused by these
    code paths.
  - Different creator's agent in same space NOT touched.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from src.models.agent import Agent, AgentScope, AgentStatus
from src.models.crew import CrewMember
from src.models.space import SpaceMember
from src.services.agent_revocation_service import (
    REASON_CREATOR_DEACTIVATED,
    REASON_CREATOR_LEFT_CREW,
    REASON_CREATOR_LEFT_SPACE,
    REASON_PERIODIC_SWEEP,
    AgentRevocationService,
)


# ---------------------------------------------------------------------------
#  Fixtures
# ---------------------------------------------------------------------------


def _agent(
    *,
    creator: uuid.UUID,
    scope: AgentScope,
    scope_id: uuid.UUID | str,
    status: str = AgentStatus.ACTIVE.value,
    space_ids: list[uuid.UUID] | None = None,
) -> Agent:
    return Agent(
        id=uuid.uuid4(),
        name=f"agent-{uuid.uuid4().hex[:6]}",
        archetype="custom",
        scope=scope.value,
        scope_id=str(scope_id),
        scope_name=None,
        status=status,
        monitor_type="question",
        focus="test",
        custom_sql=None,
        frequency="daily",
        depth="standard",
        connection_ids=[],
        space_ids=[str(s) for s in (space_ids or [])] or None,
        created_by=creator,
        identity_type="user",
    )


async def _seed_space_member(db, space_id: uuid.UUID, user_id: uuid.UUID, role: str = "member"):
    db.add(SpaceMember(space_id=space_id, user_id=user_id, role=role))
    await db.flush()


async def _seed_crew_member(db, crew_id: uuid.UUID, user_id: uuid.UUID, space_id: uuid.UUID):
    db.add(CrewMember(crew_id=crew_id, user_id=user_id, space_id=space_id))
    await db.flush()


# ---------------------------------------------------------------------------
#  Space removal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSpaceRemoval:
    async def test_space_scoped_agent_paused(self, db_session):
        creator = uuid.uuid4()
        space = uuid.uuid4()
        agent = _agent(creator=creator, scope=AgentScope.SPACE, scope_id=space)
        db_session.add(agent)
        await db_session.flush()

        result = await AgentRevocationService(db_session).revoke_on_space_removal(
            user_id=creator, space_id=space,
        )
        await db_session.refresh(agent)

        assert agent.id in result.paused_agent_ids
        assert agent.status == AgentStatus.PAUSED.value
        assert result.reason == REASON_CREATOR_LEFT_SPACE

    async def test_other_space_agent_not_paused(self, db_session):
        creator = uuid.uuid4()
        space_a = uuid.uuid4()
        space_b = uuid.uuid4()
        agent = _agent(creator=creator, scope=AgentScope.SPACE, scope_id=space_a)
        db_session.add(agent)
        await db_session.flush()

        result = await AgentRevocationService(db_session).revoke_on_space_removal(
            user_id=creator, space_id=space_b,
        )
        await db_session.refresh(agent)

        assert agent.id not in result.paused_agent_ids
        assert agent.status == AgentStatus.ACTIVE.value

    async def test_org_agent_listing_space_paused(self, db_session):
        creator = uuid.uuid4()
        space_a = uuid.uuid4()
        space_b = uuid.uuid4()
        agent = _agent(
            creator=creator,
            scope=AgentScope.ORGANIZATION,
            scope_id=uuid.uuid4(),
            space_ids=[space_a, space_b],
        )
        db_session.add(agent)
        await db_session.flush()

        result = await AgentRevocationService(db_session).revoke_on_space_removal(
            user_id=creator, space_id=space_a,
        )
        await db_session.refresh(agent)

        assert agent.id in result.paused_agent_ids
        assert agent.status == AgentStatus.PAUSED.value

    async def test_personal_agent_unaffected_by_space_removal(self, db_session):
        creator = uuid.uuid4()
        space = uuid.uuid4()
        # Personal agents are scoped to the user — not affected by space
        # membership change.
        agent = _agent(creator=creator, scope=AgentScope.PERSONAL, scope_id=creator)
        db_session.add(agent)
        await db_session.flush()

        result = await AgentRevocationService(db_session).revoke_on_space_removal(
            user_id=creator, space_id=space,
        )
        await db_session.refresh(agent)

        assert agent.id not in result.paused_agent_ids
        assert agent.status == AgentStatus.ACTIVE.value

    async def test_other_creator_agent_not_paused(self, db_session):
        """Bob's agent in the same space stays active when Alice leaves."""
        alice = uuid.uuid4()
        bob = uuid.uuid4()
        space = uuid.uuid4()
        bob_agent = _agent(creator=bob, scope=AgentScope.SPACE, scope_id=space)
        db_session.add(bob_agent)
        await db_session.flush()

        result = await AgentRevocationService(db_session).revoke_on_space_removal(
            user_id=alice, space_id=space,
        )
        await db_session.refresh(bob_agent)

        assert bob_agent.id not in result.paused_agent_ids
        assert bob_agent.status == AgentStatus.ACTIVE.value

    async def test_already_paused_agent_skipped(self, db_session):
        creator = uuid.uuid4()
        space = uuid.uuid4()
        agent = _agent(
            creator=creator, scope=AgentScope.SPACE, scope_id=space,
            status=AgentStatus.PAUSED.value,
        )
        db_session.add(agent)
        await db_session.flush()

        result = await AgentRevocationService(db_session).revoke_on_space_removal(
            user_id=creator, space_id=space,
        )
        # Service only acts on ACTIVE agents
        assert agent.id not in result.paused_agent_ids


# ---------------------------------------------------------------------------
#  Crew removal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCrewRemoval:
    async def test_crew_scoped_agent_paused(self, db_session):
        creator = uuid.uuid4()
        crew = uuid.uuid4()
        agent = _agent(creator=creator, scope=AgentScope.CREW, scope_id=crew)
        db_session.add(agent)
        await db_session.flush()

        result = await AgentRevocationService(db_session).revoke_on_crew_removal(
            user_id=creator, crew_id=crew,
        )
        await db_session.refresh(agent)

        assert agent.id in result.paused_agent_ids
        assert agent.status == AgentStatus.PAUSED.value
        assert result.reason == REASON_CREATOR_LEFT_CREW

    async def test_space_agent_not_paused_by_crew_removal(self, db_session):
        creator = uuid.uuid4()
        space = uuid.uuid4()
        crew = uuid.uuid4()
        agent = _agent(creator=creator, scope=AgentScope.SPACE, scope_id=space)
        db_session.add(agent)
        await db_session.flush()

        result = await AgentRevocationService(db_session).revoke_on_crew_removal(
            user_id=creator, crew_id=crew,
        )
        await db_session.refresh(agent)

        assert agent.id not in result.paused_agent_ids
        assert agent.status == AgentStatus.ACTIVE.value


# ---------------------------------------------------------------------------
#  User deactivation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUserDeactivation:
    async def test_every_agent_paused(self, db_session):
        creator = uuid.uuid4()
        agents = [
            _agent(creator=creator, scope=AgentScope.SPACE, scope_id=uuid.uuid4()),
            _agent(creator=creator, scope=AgentScope.CREW, scope_id=uuid.uuid4()),
            _agent(creator=creator, scope=AgentScope.PERSONAL, scope_id=creator),
        ]
        db_session.add_all(agents)
        await db_session.flush()

        result = await AgentRevocationService(db_session).revoke_on_user_deactivation(
            user_id=creator,
        )

        assert {a.id for a in agents} == set(result.paused_agent_ids)
        assert result.reason == REASON_CREATOR_DEACTIVATED

    async def test_other_users_agents_untouched(self, db_session):
        alice = uuid.uuid4()
        bob = uuid.uuid4()
        bob_agent = _agent(creator=bob, scope=AgentScope.SPACE, scope_id=uuid.uuid4())
        db_session.add(bob_agent)
        await db_session.flush()

        result = await AgentRevocationService(db_session).revoke_on_user_deactivation(
            user_id=alice,
        )
        await db_session.refresh(bob_agent)

        assert bob_agent.id not in result.paused_agent_ids
        assert bob_agent.status == AgentStatus.ACTIVE.value


# ---------------------------------------------------------------------------
#  Periodic sweep
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPeriodicSweep:
    async def test_pauses_agent_when_creator_no_longer_member(self, db_session):
        creator = uuid.uuid4()
        space = uuid.uuid4()
        agent = _agent(creator=creator, scope=AgentScope.SPACE, scope_id=space)
        db_session.add(agent)
        await db_session.flush()
        # Note: NO SpaceMember row — creator is "not a member"

        result = await AgentRevocationService(db_session).periodic_sweep()
        await db_session.refresh(agent)

        assert agent.id in result.paused_agent_ids
        assert agent.status == AgentStatus.PAUSED.value
        assert result.reason == REASON_PERIODIC_SWEEP

    async def test_keeps_agent_when_creator_is_still_member(self, db_session):
        creator = uuid.uuid4()
        space = uuid.uuid4()
        await _seed_space_member(db_session, space, creator)

        agent = _agent(creator=creator, scope=AgentScope.SPACE, scope_id=space)
        db_session.add(agent)
        await db_session.flush()

        result = await AgentRevocationService(db_session).periodic_sweep()
        await db_session.refresh(agent)

        assert agent.id not in result.paused_agent_ids
        assert agent.status == AgentStatus.ACTIVE.value

    async def test_personal_agents_skipped_by_sweep(self, db_session):
        creator = uuid.uuid4()
        agent = _agent(creator=creator, scope=AgentScope.PERSONAL, scope_id=creator)
        db_session.add(agent)
        await db_session.flush()

        result = await AgentRevocationService(db_session).periodic_sweep()
        await db_session.refresh(agent)

        # Personal agent stays — periodic sweep does not police personal scope
        assert agent.id not in result.paused_agent_ids
        assert agent.status == AgentStatus.ACTIVE.value

    async def test_service_principal_skipped(self, db_session):
        """``created_by IS NULL`` (service principal) bypasses the sweep."""
        agent = Agent(
            id=uuid.uuid4(),
            name="sp-agent",
            archetype="custom",
            scope=AgentScope.SPACE.value,
            scope_id=str(uuid.uuid4()),
            status=AgentStatus.ACTIVE.value,
            monitor_type="question",
            focus="t",
            frequency="daily",
            connection_ids=[],
            created_by=None,
            identity_type="service_principal",
        )
        db_session.add(agent)
        await db_session.flush()

        result = await AgentRevocationService(db_session).periodic_sweep()
        await db_session.refresh(agent)

        assert agent.id not in result.paused_agent_ids
        assert agent.status == AgentStatus.ACTIVE.value


# ---------------------------------------------------------------------------
#  Status reason persistence (best-effort — column may not exist)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestReasonPersistence:
    async def test_reason_set_when_column_present(self, db_session):
        creator = uuid.uuid4()
        space = uuid.uuid4()
        agent = _agent(creator=creator, scope=AgentScope.SPACE, scope_id=space)
        db_session.add(agent)
        await db_session.flush()

        await AgentRevocationService(db_session).revoke_on_space_removal(
            user_id=creator, space_id=space,
        )
        await db_session.refresh(agent)

        # Either the column exists (then it's set) or it doesn't (no-op)
        # — both are acceptable. The status itself MUST be paused.
        assert agent.status == AgentStatus.PAUSED.value
        if hasattr(agent, "status_reason") and agent.status_reason is not None:
            assert agent.status_reason == REASON_CREATOR_LEFT_SPACE
