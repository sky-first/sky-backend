#!/usr/bin/env python3
"""Phase 2.5 manual validation driver.

Loads each Crew persona from the seeded DB and asserts the
deterministic Authorization resolver returns the expected verdict for
a representative permission set. Each scenario maps 1:1 to one of the
five UX scenarios documented to the user.
"""

import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.models.crew import Crew, CrewMember
from src.models.space import Space, SpaceMember
from src.models.user import User
from src.services.authorization import Authorization

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


async def get_user(session, email: str) -> User:
    return (await session.execute(select(User).where(User.email == email))).scalar_one()


async def get_space(session, name: str) -> Space:
    return (await session.execute(select(Space).where(Space.name == name))).scalar_one()


async def get_crew(session, space_id: UUID, name: str) -> Crew:
    return (
        await session.execute(
            select(Crew).where(Crew.space_id == space_id, Crew.name == name)
        )
    ).scalar_one()


async def assert_can(
    auth: Authorization,
    label: str,
    user: User,
    permission: str,
    expected: bool,
    *,
    space_id=None,
    crew_id=None,
) -> bool:
    actual = await auth.can(user, permission, space_id=space_id, crew_id=crew_id)
    ok = actual is expected
    badge = PASS if ok else FAIL
    print(
        f"  {badge}  {label:<50}  can({permission!r}) = {actual}  (expected {expected})"
    )
    return ok


async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    failures = 0
    async with Session() as session:
        space = await get_space(session, "RBAC Demo Space")
        tax = await get_crew(session, space.id, "RBAC Tax Crew")
        audit = await get_crew(session, space.id, "RBAC Audit Crew")
        auth = Authorization(session)

        # ─── Cenário 1: viewer-crewowner — Crew escala sobre Space ───
        print("\n=== Cenário 1 — Crew owner escala sobre Space viewer ===")
        u = await get_user(session, "rbac.viewer-crewowner@example.com")
        # As space-viewer alone, owner-only actions would be denied; with
        # crew-owner active, effective is owner.
        failures += not await assert_can(
            auth,
            "viewer-crewowner: pages.delete (owner-only)",
            u,
            "pages.delete",
            True,
            space_id=space.id,
            crew_id=tax.id,
        )
        failures += not await assert_can(
            auth,
            "viewer-crewowner: spaces.members.manage (owner-only)",
            u,
            "spaces.members.manage",
            True,
            space_id=space.id,
            crew_id=tax.id,
        )
        # Without the crew context, falls back to space role = viewer
        failures += not await assert_can(
            auth,
            "viewer-crewowner: pages.delete (no crew_id) — best-crew-in-space",
            u,
            "pages.delete",
            True,  # best_crew_in_space still finds the owner Crew
            space_id=space.id,
        )

        # ─── Cenário 2: crew-only-editor — sem SpaceMember row ───
        print("\n=== Cenário 2 — Crew-only editor (sem SpaceMember) ===")
        u = await get_user(session, "rbac.crew-only-editor@example.com")
        failures += not await assert_can(
            auth,
            "crew-only-editor: connections.create (editor)",
            u,
            "connections.create",
            True,
            space_id=space.id,
            crew_id=tax.id,
        )
        failures += not await assert_can(
            auth,
            "crew-only-editor: pages.delete (owner-only) DENY",
            u,
            "pages.delete",
            False,
            space_id=space.id,
            crew_id=tax.id,
        )
        # crew_id alone (no space_id) — resolver should still grant
        failures += not await assert_can(
            auth,
            "crew-only-editor: connections.create with crew_id only",
            u,
            "connections.create",
            True,
            crew_id=tax.id,
        )

        # ─── Cenário 3: multi-crew — N crews, maior vence ───
        print("\n=== Cenário 3 — Multi-Crew (N crews da mesma Space) ===")
        u = await get_user(session, "rbac.multi-crew@example.com")
        # With Audit (owner) crew active → owner-only actions allowed
        failures += not await assert_can(
            auth,
            "multi-crew: pages.delete (Audit owner crew active)",
            u,
            "pages.delete",
            True,
            space_id=space.id,
            crew_id=audit.id,
        )
        # With Tax (viewer) crew active → still allowed because
        # best_crew_in_space picks the Audit owner role
        failures += not await assert_can(
            auth,
            "multi-crew: pages.delete with Tax viewer crew (BE max wins)",
            u,
            "pages.delete",
            True,
            space_id=space.id,
            crew_id=tax.id,
        )
        # No crew_id at all — best_crew_in_space lookup
        failures += not await assert_can(
            auth,
            "multi-crew: spaces.members.manage (no crew_id, best-crew wins)",
            u,
            "spaces.members.manage",
            True,
            space_id=space.id,
        )

        # ─── Cenário 5 — baseline (Space-only personas, sem regressão) ───
        print("\n=== Cenário 5 — baseline Space-only (regressão) ===")
        cases = [
            ("rbac.member-spaceowner@example.com", "spaces.members.manage", True),
            ("rbac.member-spaceowner@example.com", "connections.create", True),
            ("rbac.demo@example.com", "connections.create", True),
            ("rbac.demo@example.com", "spaces.members.manage", False),
            ("rbac.member-viewer@example.com", "connections.view", True),
            ("rbac.member-viewer@example.com", "connections.create", False),
        ]
        for email, perm, expected in cases:
            u = await get_user(session, email)
            label = f"{email.split('@')[0]}: {perm}"
            failures += not await assert_can(
                auth, label, u, perm, expected, space_id=space.id
            )

    print()
    if failures:
        print(f"{FAIL}  {failures} assertion(s) failed.")
        sys.exit(1)
    print(f"{PASS}  all assertions passed.")


if __name__ == "__main__":
    asyncio.run(main())
