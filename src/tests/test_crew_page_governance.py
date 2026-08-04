"""Crew page governance — G2 (create) / G3 (delete) / G4 (default protection).

Lucas's rules (2026-06-16):
  * A crew **viewer** cannot create a page; **editor+** can — and the role is
    checked against the TARGET crew, not "editor anywhere".
  * A crew page belongs to the crew: it can be deleted by its **creator** OR
    the **crew owner** — not a bare member, not a non-member platform admin.
  * The crew's **default (canonical) page** is the shared convergence anchor
    and cannot be deleted at all.
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token, get_password_hash
from src.models.crew import Crew, CrewMember
from src.models.page import Page
from src.models.space import Space, SpaceMember
from src.repositories.user import UserRepository


def _hdr(user) -> dict:
    return {
        "Authorization": "Bearer "
        + create_access_token({"sub": str(user.id), "email": user.email, "role": user.role})
    }


async def _user(db: AsyncSession, name: str, role: str = "user"):
    return await UserRepository(db).create(
        email=f"{name}-{uuid.uuid4().hex[:6]}@x.com",
        password_hash=get_password_hash("pw"),
        name=name,
        role=role,
    )


async def _seed(db: AsyncSession) -> dict:
    """Space + crew A (owner/editor/viewer) + crew B (an editor not in A)."""
    owner = await _user(db, "owner")
    space = Space(name="S", created_by=owner.id)
    db.add(space)
    await db.flush()
    db.add(SpaceMember(space_id=space.id, user_id=owner.id, role="owner"))

    crew = Crew(name="A", space_id=space.id, created_by=owner.id)
    db.add(crew)
    await db.flush()
    editor = await _user(db, "editor")
    viewer = await _user(db, "viewer")
    db.add(CrewMember(crew_id=crew.id, user_id=owner.id, role="owner"))
    db.add(CrewMember(crew_id=crew.id, user_id=editor.id, role="editor"))
    db.add(CrewMember(crew_id=crew.id, user_id=viewer.id, role="viewer"))

    crew_b = Crew(name="B", space_id=space.id, created_by=owner.id)
    db.add(crew_b)
    await db.flush()
    other_editor = await _user(db, "otheredit")
    db.add(CrewMember(crew_id=crew_b.id, user_id=other_editor.id, role="editor"))

    await db.commit()
    return {
        "space": space, "crew": crew, "crew_b": crew_b, "owner": owner,
        "editor": editor, "viewer": viewer, "other_editor": other_editor,
    }


def _body(crew_id, name="P") -> dict:
    return {"name": name, "type": "team", "color": "#3b82f6", "crew_id": str(crew_id)}


async def _crew_page(db: AsyncSession, crew, owner_id, name, created_at) -> Page:
    page = Page(
        name=name, type="team", color="#3b82f6",
        owner_id=owner_id, crew_id=crew.id, created_at=created_at,
    )
    db.add(page)
    await db.flush()
    return page


# ─── G2: create gated on the TARGET crew's role ──────────────────────────────


@pytest.mark.asyncio
async def test_crew_editor_can_create_page(async_client: AsyncClient, db_session: AsyncSession):
    s = await _seed(db_session)
    r = await async_client.post("/api/v1/pages", json=_body(s["crew"].id), headers=_hdr(s["editor"]))
    assert r.status_code == status.HTTP_201_CREATED, r.text


@pytest.mark.asyncio
async def test_crew_viewer_cannot_create_page(async_client: AsyncClient, db_session: AsyncSession):
    s = await _seed(db_session)
    r = await async_client.post("/api/v1/pages", json=_body(s["crew"].id), headers=_hdr(s["viewer"]))
    assert r.status_code == status.HTTP_403_FORBIDDEN, r.text


@pytest.mark.asyncio
async def test_editor_of_other_crew_cannot_create_here(async_client: AsyncClient, db_session: AsyncSession):
    """Cross-crew privilege leak (G2): editor of crew B, not a member of crew
    A, must NOT be able to create a page in crew A."""
    s = await _seed(db_session)
    r = await async_client.post("/api/v1/pages", json=_body(s["crew"].id), headers=_hdr(s["other_editor"]))
    assert r.status_code == status.HTTP_403_FORBIDDEN, r.text


# ─── G3: delete = creator OR crew owner ──────────────────────────────────────


@pytest.mark.asyncio
async def test_creator_editor_deletes_own_nondefault_page(async_client: AsyncClient, db_session: AsyncSession):
    s = await _seed(db_session)
    await _crew_page(db_session, s["crew"], s["owner"].id, "Default", datetime(2026, 1, 1, tzinfo=timezone.utc))
    mine = await _crew_page(db_session, s["crew"], s["editor"].id, "Mine", datetime(2026, 1, 2, tzinfo=timezone.utc))
    await db_session.commit()
    r = await async_client.delete(f"/api/v1/pages/{mine.id}", headers=_hdr(s["editor"]))
    assert r.status_code == status.HTTP_200_OK, r.text


@pytest.mark.asyncio
async def test_crew_owner_deletes_others_nondefault_page(async_client: AsyncClient, db_session: AsyncSession):
    s = await _seed(db_session)
    await _crew_page(db_session, s["crew"], s["owner"].id, "Default", datetime(2026, 1, 1, tzinfo=timezone.utc))
    page = await _crew_page(db_session, s["crew"], s["editor"].id, "Editor's", datetime(2026, 1, 2, tzinfo=timezone.utc))
    await db_session.commit()
    r = await async_client.delete(f"/api/v1/pages/{page.id}", headers=_hdr(s["owner"]))
    assert r.status_code == status.HTTP_200_OK, r.text


@pytest.mark.asyncio
async def test_noncreator_editor_cannot_delete_others_page(async_client: AsyncClient, db_session: AsyncSession):
    s = await _seed(db_session)
    await _crew_page(db_session, s["crew"], s["owner"].id, "Default", datetime(2026, 1, 1, tzinfo=timezone.utc))
    page = await _crew_page(db_session, s["crew"], s["owner"].id, "Owner's", datetime(2026, 1, 2, tzinfo=timezone.utc))
    await db_session.commit()
    # editor is a crew member but neither the creator nor the crew owner.
    r = await async_client.delete(f"/api/v1/pages/{page.id}", headers=_hdr(s["editor"]))
    assert r.status_code == status.HTTP_403_FORBIDDEN, r.text


@pytest.mark.asyncio
async def test_viewer_cannot_delete_page(async_client: AsyncClient, db_session: AsyncSession):
    s = await _seed(db_session)
    await _crew_page(db_session, s["crew"], s["owner"].id, "Default", datetime(2026, 1, 1, tzinfo=timezone.utc))
    page = await _crew_page(db_session, s["crew"], s["editor"].id, "P2", datetime(2026, 1, 2, tzinfo=timezone.utc))
    await db_session.commit()
    r = await async_client.delete(f"/api/v1/pages/{page.id}", headers=_hdr(s["viewer"]))
    assert r.status_code == status.HTTP_403_FORBIDDEN, r.text


@pytest.mark.asyncio
async def test_non_member_cannot_delete_crew_page(async_client: AsyncClient, db_session: AsyncSession):
    """other_editor belongs to crew B only — deleting a crew A page is denied."""
    s = await _seed(db_session)
    await _crew_page(db_session, s["crew"], s["owner"].id, "Default", datetime(2026, 1, 1, tzinfo=timezone.utc))
    page = await _crew_page(db_session, s["crew"], s["editor"].id, "P2", datetime(2026, 1, 2, tzinfo=timezone.utc))
    await db_session.commit()
    r = await async_client.delete(f"/api/v1/pages/{page.id}", headers=_hdr(s["other_editor"]))
    assert r.status_code == status.HTTP_403_FORBIDDEN, r.text


# ─── G4: the default (canonical) page is protected ───────────────────────────


@pytest.mark.asyncio
async def test_default_crew_page_cannot_be_deleted_by_owner(async_client: AsyncClient, db_session: AsyncSession):
    s = await _seed(db_session)
    # Oldest crew page = the canonical default (the convergence anchor).
    default = await _crew_page(db_session, s["crew"], s["owner"].id, "Team Canvas", datetime(2026, 1, 1, tzinfo=timezone.utc))
    await _crew_page(db_session, s["crew"], s["editor"].id, "Second", datetime(2026, 1, 2, tzinfo=timezone.utc))
    await db_session.commit()
    # Even the crew owner cannot delete the default page.
    r = await async_client.delete(f"/api/v1/pages/{default.id}", headers=_hdr(s["owner"]))
    assert r.status_code == status.HTTP_403_FORBIDDEN, r.text
