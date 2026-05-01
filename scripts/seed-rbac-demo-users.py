#!/usr/bin/env python3
"""Seed local DB with one canonical user per RBAC role pair.

Run: python scripts/seed-rbac-demo-users.py

Creates / upserts the full 3×3 cross-axis matrix plus the 3 no-space
platform pivots (12 users total). Email naming convention:
`rbac.<platform>[-<context>]@example.com`.

Platform-only (no Space membership):
  • rbac.owner@…                  user.role=owner    (no space)
  • rbac.admin@…                  user.role=admin    (no space)
  • rbac.member@…                 user.role=member   (no space → Personal)

Cross-axis (member of "RBAC Demo Space" with the listed Space role).
Vocabulary is the new owner/editor/viewer (was commander/navigator/explorer):
  • rbac.owner-spaceowner@…   platform owner   + Space owner
  • rbac.owner-editor@…       platform owner   + Space editor
  • rbac.owner-viewer@…       platform owner   + Space viewer
  • rbac.admin-spaceowner@…   platform admin   + Space owner
  • rbac.admin-editor@…       platform admin   + Space editor
  • rbac.admin-viewer@…       platform admin   + Space viewer
  • rbac.member-spaceowner@…  platform member  + Space owner
  • rbac.demo@…               platform member  + Space editor   (Demo flow)
  • rbac.member-viewer@…      platform member  + Space viewer

Phase 2.5 — Crew layer personas (sub-team membership inside the demo
Space). All three are platform `member`; the Crew membership decides
their effective access via max(spaceRole, crewRole):
  • rbac.crew-only-editor@…   no SpaceMember row,
                              CrewMember(role=editor) in "RBAC Tax Crew"
  • rbac.viewer-crewowner@…   SpaceMember(role=viewer) +
                              CrewMember(role=owner) in "RBAC Tax Crew"
  • rbac.multi-crew@…         no SpaceMember row, two crews:
                              "RBAC Tax Crew"  → viewer
                              "RBAC Audit Crew" → owner   (highest wins)

Auth: password login is disabled in production (SSO + public demo
only). For local visual validation use `scripts/impersonate-rbac-user.py`
which signs a JWT against the local BE secret and prints a devtools
snippet you paste into the browser. The `password_hash` column on each
row is set to a random throwaway value to satisfy the NOT NULL
constraint — nobody ever logs in with a password.

Each row is idempotent: rerun is safe and only patches the role +
Space membership back to the canonical values.
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import secrets

from src.core.security import get_password_hash
from src.models.crew import Crew, CrewMember
from src.models.page import Page  # noqa: F401 — register relationship
from src.models.space import Space, SpaceMember
from src.models.user import User
from src.models.workspace import Workspace  # noqa: F401 — register relationship
from src.services.onboarding_service import ensure_default_page_and_space


# Password login is disabled in production. The hash is only here to
# satisfy the NOT NULL constraint on `users.password_hash`. Generate a
# fresh random one each run so it cannot be guessed and so anyone who
# tries to "log in with the password" gets a clear failure.
def _throwaway_hash() -> str:
    return get_password_hash(secrets.token_urlsafe(32))

USERS = [
    # Platform-only (no Space) — owner/admin bypass Space gates; member → Personal.
    ("rbac.owner@example.com",         "owner",  "RBAC Owner",          None),
    ("rbac.admin@example.com",         "admin",  "RBAC Admin",          None),
    ("rbac.member@example.com",        "member", "RBAC Member",         None),
    # Full 3×3 platform × Space-role cross-axis (rbac.<plat>-<sr>@…).
    # NEW vocabulary: owner / editor / viewer (was commander/navigator/explorer).
    ("rbac.owner-spaceowner@example.com",  "owner",  "RBAC Owner / Space Owner",  "owner"),
    ("rbac.owner-editor@example.com",      "owner",  "RBAC Owner / Editor",       "editor"),
    ("rbac.owner-viewer@example.com",      "owner",  "RBAC Owner / Viewer",       "viewer"),
    ("rbac.admin-spaceowner@example.com",  "admin",  "RBAC Admin / Space Owner",  "owner"),
    ("rbac.admin-editor@example.com",      "admin",  "RBAC Admin / Editor",       "editor"),
    ("rbac.admin-viewer@example.com",      "admin",  "RBAC Admin / Viewer",       "viewer"),
    ("rbac.member-spaceowner@example.com", "member", "RBAC Member / Space Owner", "owner"),
    ("rbac.demo@example.com",              "member", "RBAC Demo Visitor",         "editor"),
    ("rbac.member-viewer@example.com",     "member", "RBAC Member / Viewer",      "viewer"),
]

# Phase 2.5 — Crew personas. The 4-tuple is repurposed for these rows:
#   (email, platform_role, name, space_role_or_None_if_crew_only)
CREW_USERS = [
    ("rbac.crew-only-editor@example.com",  "member", "RBAC Crew-Only Editor",     None),
    ("rbac.viewer-crewowner@example.com",  "member", "RBAC Viewer / Crew Owner",  "viewer"),
    ("rbac.multi-crew@example.com",        "member", "RBAC Multi-Crew Member",    None),
]
SPACE_NAME = "RBAC Demo Space"
TAX_CREW_NAME = "RBAC Tax Crew"
AUDIT_CREW_NAME = "RBAC Audit Crew"


async def upsert_user(session, email, role, name):
    existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing:
        existing.password_hash = _throwaway_hash()
        existing.role = role
        existing.name = name
        await session.flush()
        return existing
    user = User(
        email=email,
        password_hash=_throwaway_hash(),
        name=name,
        role=role,
    )
    session.add(user)
    await session.flush()
    await ensure_default_page_and_space(session, user)
    return user


async def upsert_demo_space(session, owner_admin):
    existing = (
        await session.execute(select(Space).where(Space.name == SPACE_NAME))
    ).scalar_one_or_none()
    if existing:
        return existing
    space = Space(name=SPACE_NAME, description="RBAC e2e demo space", created_by=owner_admin.id)
    session.add(space)
    await session.flush()
    return space


async def upsert_membership(session, user, space, context_role):
    existing = (
        await session.execute(
            select(SpaceMember).where(
                SpaceMember.user_id == user.id,
                SpaceMember.space_id == space.id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.role = context_role
        return
    session.add(SpaceMember(user_id=user.id, space_id=space.id, role=context_role))


async def upsert_crew(session, space, owner, name):
    existing = (
        await session.execute(
            select(Crew).where(Crew.space_id == space.id, Crew.name == name)
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    crew = Crew(name=name, space_id=space.id, created_by=owner.id)
    session.add(crew)
    await session.flush()
    return crew


async def upsert_crew_membership(session, user, crew, role):
    existing = (
        await session.execute(
            select(CrewMember).where(
                CrewMember.user_id == user.id,
                CrewMember.crew_id == crew.id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.role = role
        return
    session.add(CrewMember(user_id=user.id, crew_id=crew.id, role=role))


async def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("Set DATABASE_URL first (e.g. via .env.local).")
        sys.exit(1)

    engine = create_async_engine(db_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        users = {}
        for email, role, name, _ in USERS:
            users[email] = await upsert_user(session, email, role, name)
        for email, role, name, _ in CREW_USERS:
            users[email] = await upsert_user(session, email, role, name)

        admin = users["rbac.admin@example.com"]
        space = await upsert_demo_space(session, admin)

        for email, _, _, context_role in USERS:
            if context_role:
                await upsert_membership(session, users[email], space, context_role)

        # Phase 2.5 — Crew personas
        tax_crew = await upsert_crew(session, space, admin, TAX_CREW_NAME)
        audit_crew = await upsert_crew(session, space, admin, AUDIT_CREW_NAME)

        await upsert_crew_membership(
            session, users["rbac.crew-only-editor@example.com"], tax_crew, "editor"
        )
        viewer_crewowner = users["rbac.viewer-crewowner@example.com"]
        await upsert_membership(session, viewer_crewowner, space, "viewer")
        await upsert_crew_membership(session, viewer_crewowner, tax_crew, "owner")

        multi = users["rbac.multi-crew@example.com"]
        await upsert_crew_membership(session, multi, tax_crew, "viewer")
        await upsert_crew_membership(session, multi, audit_crew, "owner")

        await session.commit()

    print("✅ Seed complete.")
    print("   Auth: password login is disabled. Use")
    print("   `scripts/impersonate-rbac-user.py <email>` to drop into a persona.")
    print()
    for email, role, _, ctx in USERS:
        ctx_str = f"  (Space '{SPACE_NAME}': {ctx})" if ctx else ""
        print(f"   {role:8}  {email}{ctx_str}")
    print()
    print("   Phase 2.5 — Crew personas (Space '{}'):".format(SPACE_NAME))
    print(f"   member   rbac.crew-only-editor@example.com  ({TAX_CREW_NAME}: editor)")
    print(
        f"   member   rbac.viewer-crewowner@example.com  (Space: viewer, {TAX_CREW_NAME}: owner)"
    )
    print(
        f"   member   rbac.multi-crew@example.com        ({TAX_CREW_NAME}: viewer, {AUDIT_CREW_NAME}: owner)"
    )


if __name__ == "__main__":
    asyncio.run(main())
