#!/usr/bin/env python3
"""Seed local DB with one canonical user per RBAC role pair.

Run: python scripts/seed-rbac-demo-users.py

Creates / upserts the full 3×3 cross-axis matrix plus the 3 no-space
platform pivots (12 users total). Email naming convention:
`rbac.<platform>[-<context>]@skyfirstlabs.local`.

Platform-only (no Space membership):
  • rbac.owner@…                  user.role=owner    (no space)
  • rbac.admin@…                  user.role=admin    (no space)
  • rbac.member@…                 user.role=member   (no space → Personal)

Cross-axis (member of "RBAC Demo Space" with the listed context role):
  • rbac.owner-commander@…        owner   + commander
  • rbac.owner-navigator@…        owner   + navigator
  • rbac.owner-explorer@…         owner   + explorer
  • rbac.admin-commander@…        admin   + commander
  • rbac.admin-navigator@…        admin   + navigator
  • rbac.admin-explorer@…         admin   + explorer
  • rbac.member-commander@…       member  + commander
  • rbac.demo@…                   member  + navigator   (the actual Demo flow)
  • rbac.member-explorer@…        member  + explorer

Common password for all of them: Test@2026!Secure

Each row is idempotent: rerun is safe and only patches the password +
role + Space membership back to the canonical values.
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.core.security import get_password_hash
from src.models.page import Page  # noqa: F401 — register relationship
from src.models.space import Space, SpaceMember
from src.models.user import User
from src.models.workspace import Workspace  # noqa: F401 — register relationship
from src.services.onboarding_service import ensure_default_page_and_space


PASSWORD = "Test@2026!Secure"

USERS = [
    # Platform-only (no Space) — owner/admin bypass Space gates; member → Personal.
    ("rbac.owner@skyfirstlabs.local",            "owner",  "RBAC Owner",            None),
    ("rbac.admin@skyfirstlabs.local",            "admin",  "RBAC Admin",            None),
    ("rbac.member@skyfirstlabs.local",           "member", "RBAC Member",           None),
    # Full 3×3 platform × context cross-axis (rbac.<plat>-<ctx>@…).
    ("rbac.owner-commander@skyfirstlabs.local",  "owner",  "RBAC Owner Commander",  "commander"),
    ("rbac.owner-navigator@skyfirstlabs.local",  "owner",  "RBAC Owner Navigator",  "navigator"),
    ("rbac.owner-explorer@skyfirstlabs.local",   "owner",  "RBAC Owner Explorer",   "explorer"),
    ("rbac.admin-commander@skyfirstlabs.local",  "admin",  "RBAC Admin Commander",  "commander"),
    ("rbac.admin-navigator@skyfirstlabs.local",  "admin",  "RBAC Admin Navigator",  "navigator"),
    ("rbac.admin-explorer@skyfirstlabs.local",   "admin",  "RBAC Admin Explorer",   "explorer"),
    ("rbac.member-commander@skyfirstlabs.local", "member", "RBAC Member Commander", "commander"),
    ("rbac.demo@skyfirstlabs.local",             "member", "RBAC Demo Visitor",     "navigator"),
    ("rbac.member-explorer@skyfirstlabs.local",  "member", "RBAC Member Explorer",  "explorer"),
]
SPACE_NAME = "RBAC Demo Space"


async def upsert_user(session, email, role, name):
    existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing:
        existing.password_hash = get_password_hash(PASSWORD)
        existing.role = role
        existing.name = name
        await session.flush()
        return existing
    user = User(
        email=email,
        password_hash=get_password_hash(PASSWORD),
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

        admin = users["rbac.admin@skyfirstlabs.local"]
        space = await upsert_demo_space(session, admin)

        for email, _, _, context_role in USERS:
            if context_role:
                await upsert_membership(session, users[email], space, context_role)

        await session.commit()

    print("✅ Seed complete.")
    print(f"   Common password: {PASSWORD}")
    for email, role, _, ctx in USERS:
        ctx_str = f"  (Space '{SPACE_NAME}': {ctx})" if ctx else ""
        print(f"   {role:8}  {email}{ctx_str}")


if __name__ == "__main__":
    asyncio.run(main())
