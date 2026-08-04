"""Defensive auto-create of crew service principals (Lucas QA 2026-05-30).

The April 2026 migration introduced ServicePrincipal rows for every
Space and every Crew. Crews created BEFORE that migration do not have
an SP, and `resolve_identity_for_page` used to raise
``NotFoundError("invariant violation")`` for them — which surfaced as a
500 the moment any user tried to drop an agent widget on a legacy crew
page (Lucas's bug report).

The function now lazy-creates the SP on the fly for both Space and Crew
branches, matching the defensive path already used for Space. The
assertion is preserved as code commentary; this test pins the behaviour.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.agent_identity import resolve_identity_for_page
from src.core.security import get_password_hash
from src.models.crew import Crew, CrewMember
from src.models.page import Page
from src.models.service_principal import ServicePrincipal
from src.models.space import Space
from src.repositories.user import UserRepository


async def _make_user(db: AsyncSession, email="legacy@x.com"):
    repo = UserRepository(db)
    user = await repo.create(
        email=email,
        password_hash=get_password_hash("pw"),
        name="Legacy",
        role="user",
    )
    await db.commit()
    return user


@pytest.mark.asyncio
async def test_crew_page_without_sp_auto_creates_one(
    test_user_with_tokens: dict, db_session: AsyncSession
):
    """A crew without an SP (legacy migration gap) must get one created
    on-demand, instead of raising the old invariant-violation 500."""
    user = test_user_with_tokens["user"]

    # Bare-bones Space + Crew without going through the service layer,
    # so no SP is auto-created.
    space = Space(name="legacy-host", created_by=user.id)
    db_session.add(space)
    await db_session.commit()
    await db_session.refresh(space)

    crew = Crew(name="legacy-crew", space_id=space.id, created_by=user.id)
    db_session.add(crew)
    await db_session.commit()
    await db_session.refresh(crew)
    db_session.add(CrewMember(crew_id=crew.id, user_id=user.id, role="owner"))
    await db_session.commit()

    # Confirm no SP exists yet.
    pre = (
        await db_session.execute(
            select(ServicePrincipal).where(ServicePrincipal.crew_id == crew.id)
        )
    ).scalar_one_or_none()
    assert pre is None

    page = Page(
        name="legacy page",
        type="team",
        color="#3b82f6",
        owner_id=user.id,
        space_id=space.id,
        crew_id=crew.id,
    )
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)

    resolved = await resolve_identity_for_page(
        db=db_session, page_id=page.id, creator_user_id=user.id
    )

    # Identity must be the (now newly minted) SP, not the creator.
    assert resolved.identity_type == "service_principal"
    assert resolved.crew_id == crew.id
    assert resolved.attributed_to_user_id == user.id

    # And the SP must be persisted, named in the canonical sa-crew-* form.
    sp = (
        await db_session.execute(
            select(ServicePrincipal).where(ServicePrincipal.crew_id == crew.id)
        )
    ).scalar_one_or_none()
    assert sp is not None
    assert sp.name.startswith("sa-crew-")
