"""Tests for agent identity resolution + lifecycle — Phase 1 iteration 1.4.

Use cases covered (docs/agent-and-ai-master-plan.md §10 C):
  C1   Personal page → runs as creator user
  C2   Crew page → runs as sp-crew-{id}
  C3   Space page → runs as sp-space-{id}; SP auto-created on space creation
  C6   Crew delete → agents in that crew move to status='ended'
  C6'  Space delete → agents in that space move to status='ended'

C4 (member leaves) and C5 (user leaves org) are lifecycle event hooks
deferred to a later iteration when we have the notification producer
wired to route "creator unavailable" alerts. C7 (HMAC) is iteration 1.2.
C8 (audit fields) is iteration 1.1.
"""

import uuid as _uuid
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.agent_identity import ResolvedIdentity, resolve_identity_for_page
from src.core.exceptions import NotFoundError
from src.core.security import get_password_hash
from src.models.agent import Agent
from src.models.crew import Crew, CrewMember
from src.models.page import Page
from src.models.service_principal import ServicePrincipal
from src.models.space import Space, SpaceMember
from src.repositories.user import UserRepository


# ─── Fixtures ─────────────────────────────────────────────────────────────


async def _make_user(db: AsyncSession, email="ident@x.com"):
    repo = UserRepository(db)
    user = await repo.create(
        email=email,
        password_hash=get_password_hash("pw"),
        name=email.split("@")[0],
        role="user",
    )
    await db.commit()
    return user


async def _make_space_with_sp(db: AsyncSession, owner_id, name="S"):
    """Create a space + its SP the way `SpaceService.create_space` does."""
    space = Space(name=name, created_by=owner_id)
    db.add(space)
    await db.commit()
    await db.refresh(space)
    sp = ServicePrincipal(
        space_id=space.id, name=f"sa-space-{str(space.id)[:8]}"
    )
    db.add(sp)
    db.add(SpaceMember(space_id=space.id, user_id=owner_id))
    await db.commit()
    return space, sp


async def _make_crew_with_sp(db: AsyncSession, space_id, owner_id, name="C"):
    crew = Crew(name=name, space_id=space_id, created_by=owner_id)
    db.add(crew)
    await db.commit()
    await db.refresh(crew)
    sp = ServicePrincipal(crew_id=crew.id, name=f"sa-crew-{str(crew.id)[:8]}")
    db.add(sp)
    db.add(CrewMember(crew_id=crew.id, user_id=owner_id, role="commander"))
    await db.commit()
    return crew, sp


async def _make_page(db: AsyncSession, *, owner_id, space_id=None, crew_id=None):
    page = Page(
        name="P",
        type="personal" if space_id is None and crew_id is None else "team",
        color="#3b82f6",
        owner_id=owner_id,
        space_id=space_id,
        crew_id=crew_id,
    )
    db.add(page)
    await db.commit()
    await db.refresh(page)
    return page


# ─── C1: personal page → user ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_personal_page_resolves_to_user(
    test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    page = await _make_page(db_session, owner_id=user.id)

    resolved = await resolve_identity_for_page(
        db=db_session, page_id=page.id, creator_user_id=user.id
    )

    assert resolved.identity_type == "user"
    assert resolved.identity_id == user.id
    assert resolved.attributed_to_user_id == user.id
    assert resolved.space_id is None
    assert resolved.crew_id is None


# ─── C2: crew page → sp-crew ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_crew_page_resolves_to_crew_service_principal(
    test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    space, _ = await _make_space_with_sp(db_session, user.id)
    crew, crew_sp = await _make_crew_with_sp(db_session, space.id, user.id)
    page = await _make_page(db_session, owner_id=user.id, space_id=space.id, crew_id=crew.id)

    resolved = await resolve_identity_for_page(
        db=db_session, page_id=page.id, creator_user_id=user.id
    )

    assert resolved.identity_type == "service_principal"
    assert resolved.identity_id == crew_sp.id
    assert resolved.attributed_to_user_id == user.id
    assert resolved.crew_id == crew.id


# ─── C3: space page → sp-space + auto-create on space creation ────────────


@pytest.mark.asyncio
async def test_space_page_resolves_to_space_service_principal(
    test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    space, space_sp = await _make_space_with_sp(db_session, user.id)
    page = await _make_page(db_session, owner_id=user.id, space_id=space.id)

    resolved = await resolve_identity_for_page(
        db=db_session, page_id=page.id, creator_user_id=user.id
    )

    assert resolved.identity_type == "service_principal"
    assert resolved.identity_id == space_sp.id
    assert resolved.attributed_to_user_id == user.id
    assert resolved.space_id == space.id
    assert resolved.crew_id is None


@pytest.mark.asyncio
async def test_space_service_auto_creates_service_principal(
    test_user_with_tokens: dict, db_session: AsyncSession
):
    """C3 — SpaceService.create_space creates one SP per space automatically."""
    from src.schemas.space import SpaceCreate
    from src.services.space_service import SpaceService

    user = test_user_with_tokens["user"]
    svc = SpaceService(db_session)

    space_resp = await svc.create_space(
        user=user,
        space_data=SpaceCreate(name="Auto SP test"),
    )

    sp = (
        await db_session.execute(
            select(ServicePrincipal).where(ServicePrincipal.space_id == space_resp.id)
        )
    ).scalar_one_or_none()
    assert sp is not None
    assert sp.name.startswith("sa-space-")
    assert sp.active is True


# ─── Precedence: crew wins over space when both are set ───────────────────


@pytest.mark.asyncio
async def test_crew_scope_takes_precedence_over_space(
    test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    space, space_sp = await _make_space_with_sp(db_session, user.id)
    crew, crew_sp = await _make_crew_with_sp(db_session, space.id, user.id)
    page = await _make_page(
        db_session, owner_id=user.id, space_id=space.id, crew_id=crew.id
    )

    resolved = await resolve_identity_for_page(
        db=db_session, page_id=page.id, creator_user_id=user.id
    )

    # More specific (crew) wins.
    assert resolved.identity_id == crew_sp.id
    assert resolved.identity_id != space_sp.id


# ─── Error paths ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_nonexistent_page_raises_not_found(
    test_user_with_tokens: dict, db_session: AsyncSession
):
    user = test_user_with_tokens["user"]
    with pytest.raises(NotFoundError):
        await resolve_identity_for_page(
            db=db_session,
            page_id=_uuid.uuid4(),
            creator_user_id=user.id,
        )


@pytest.mark.asyncio
async def test_space_page_without_sp_raises_not_found(
    test_user_with_tokens: dict, db_session: AsyncSession
):
    """Invariant violation: if a space has no SP (shouldn't happen after
    the migration backfill + auto-create), we refuse to fall back to the
    creator user — that would be a silent security hole."""
    user = test_user_with_tokens["user"]
    # Create a space WITHOUT going through SpaceService, so no SP is made
    space = Space(name="Bare space", created_by=user.id)
    db_session.add(space)
    await db_session.commit()
    await db_session.refresh(space)
    page = await _make_page(db_session, owner_id=user.id, space_id=space.id)

    with pytest.raises(NotFoundError, match="service principal"):
        await resolve_identity_for_page(
            db=db_session, page_id=page.id, creator_user_id=user.id
        )


# ─── C6: lifecycle — crew/space delete ends agents ────────────────────────


@pytest.mark.asyncio
async def test_space_delete_ends_space_agents(
    test_user_with_tokens: dict, db_session: AsyncSession
):
    from src.services.space_service import SpaceService
    from src.schemas.space import SpaceCreate

    user = test_user_with_tokens["user"]
    svc = SpaceService(db_session)
    space_resp = await svc.create_space(
        user=user, space_data=SpaceCreate(name="to delete")
    )

    # Seed two agents: one in this space (should end), one unrelated (stays)
    a_doomed = Agent(
        name="doomed", archetype="custom", scope="space", scope_id=str(space_resp.id),
        status="active", frequency="daily", connection_ids=[], created_by=user.id,
    )
    a_survivor = Agent(
        name="survivor", archetype="custom", scope="space", scope_id=str(_uuid.uuid4()),
        status="active", frequency="daily", connection_ids=[], created_by=user.id,
    )
    db_session.add_all([a_doomed, a_survivor])
    await db_session.commit()

    await svc.delete_space(space_id=space_resp.id, user=user)

    doomed = (
        await db_session.execute(select(Agent).where(Agent.id == a_doomed.id))
    ).scalar_one()
    survivor = (
        await db_session.execute(select(Agent).where(Agent.id == a_survivor.id))
    ).scalar_one()

    assert doomed.status == "ended"
    assert survivor.status == "active"


@pytest.mark.asyncio
async def test_crew_delete_ends_crew_agents(
    test_user_with_tokens: dict, db_session: AsyncSession
):
    from src.services.crew_service import CrewService
    from src.schemas.crew import CrewCreate
    from src.services.space_service import SpaceService
    from src.schemas.space import SpaceCreate

    user = test_user_with_tokens["user"]
    space_svc = SpaceService(db_session)
    space = await space_svc.create_space(
        user=user, space_data=SpaceCreate(name="Host space")
    )

    crew_svc = CrewService(db_session)
    crew = await crew_svc.create_crew(
        user=user, crew_data=CrewCreate(name="CtoDelete", space_id=space.id)
    )

    doomed = Agent(
        name="d", archetype="custom", scope="crew", scope_id=str(crew.id),
        status="active", frequency="daily", connection_ids=[], created_by=user.id,
    )
    db_session.add(doomed)
    await db_session.commit()

    await crew_svc.delete_crew(crew_id=crew.id, user=user)

    doomed = (
        await db_session.execute(select(Agent).where(Agent.id == doomed.id))
    ).scalar_one()
    assert doomed.status == "ended"
