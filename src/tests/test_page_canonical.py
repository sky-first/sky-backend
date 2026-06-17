"""Canonical-page-per-crew tests (Phase 2)."""

import uuid

import pytest

from src.core.exceptions import ForbiddenError
from src.models.space import Space
from src.models.user import User
from src.schemas.crew import CrewCreate
from src.services.crew_service import CrewService
from src.services.page_service import PageService


async def _make_crew(db_session, crew_name: str = "Finance"):
    user = User(
        id=uuid.uuid4(),
        email=f"canon.{uuid.uuid4().hex[:8]}@example.com",
        role="user",
        password_hash="dummy",
        name="Canon User",
    )
    space = Space(id=uuid.uuid4(), name="Canon Space", created_by=user.id)
    db_session.add_all([user, space])
    await db_session.flush()
    crew = await CrewService(db_session).create_crew(
        user, CrewCreate(name=crew_name, space_id=space.id)
    )
    return user, crew


@pytest.mark.asyncio
async def test_ensure_creates_named_canonical_page(db_session):
    user, crew = await _make_crew(db_session, "Finance")
    svc = PageService(db_session)

    page = await svc.ensure_default_crew_page(crew.id, user)

    assert page.is_canonical is True
    assert page.name == "Finance Page"  # named after the crew
    assert str(page.crew_id) == str(crew.id)


@pytest.mark.asyncio
async def test_ensure_is_idempotent_same_page(db_session):
    user, crew = await _make_crew(db_session)
    svc = PageService(db_session)

    first = await svc.ensure_default_crew_page(crew.id, user)
    second = await svc.ensure_default_crew_page(crew.id, user)

    # Convergence: same canonical page id on every call (the bug this fixes).
    assert first.id == second.id


@pytest.mark.asyncio
async def test_canonical_page_cannot_be_deleted(db_session):
    user, crew = await _make_crew(db_session)
    svc = PageService(db_session)

    page = await svc.ensure_default_crew_page(crew.id, user)

    with pytest.raises(ForbiddenError):
        await svc.delete_page(page.id, user)
