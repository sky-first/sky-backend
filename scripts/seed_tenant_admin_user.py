"""Seed an admin user inside a tenant DB.

Companion to ``scripts/seed_tenant_registry.py`` from PR #519. Whereas
``seed_tenant_registry`` writes the routing row, this script provisions
the first human who can log in: a row in the tenant DB's ``users``
table with ``role=admin``, ``email_verified=True``,
``has_completed_onboarding=True``, and a known password hash.

Designed to run inside the onboard-client workflow's migrate Job
(Model B) so a freshly minted tenant lands with a working account out
of the box. The workflow generates a random password, runs alembic,
runs this script, and posts the password back to the BE via the
report-phase webhook so the Console can surface it to the operator.

Env vars (all required):

    DATABASE_URL              — tenant DB (asyncpg or psycopg2 URL)
    TENANT_ADMIN_EMAIL        — e.g. ``lucas.ventura@gbtsolutions.pt``
    TENANT_ADMIN_PASSWORD     — plaintext (will be bcrypted)
    TENANT_ADMIN_NAME         — optional display name; defaults to "Admin"

Idempotent: an existing user with the same email is refreshed (new
password hash + role=admin) so re-running the migrate Job after a
schema bump doesn't leave dual accounts.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

# Pull in the model registry so the User mapper resolves cleanly.
import src.models  # noqa: F401, E402
from src.core.security import get_password_hash  # noqa: E402
from src.models.user import User  # noqa: E402


def _require(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"{name} env var required")
    return v


def _prepare_async_url(url: str) -> str:
    """Strip libpq ``sslmode`` and force ``+asyncpg`` so the same URL
    works for both Alembic (psycopg2) and SQLAlchemy/asyncpg without
    further surgery."""
    if "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    parsed = urlparse(url)
    if not parsed.query:
        return url
    keep = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if k != "sslmode"]
    return urlunparse(parsed._replace(query=urlencode(keep)))


async def main() -> int:
    db_url = _prepare_async_url(_require("DATABASE_URL"))
    email = _require("TENANT_ADMIN_EMAIL").strip().lower()
    password = _require("TENANT_ADMIN_PASSWORD")
    name = os.environ.get("TENANT_ADMIN_NAME") or "Admin"

    engine = create_async_engine(db_url, echo=False)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sm() as session:
            existing = (
                await session.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            # First-user-of-a-tenant lands as ``admin`` — the tenant-level
            # role that can invite other users, edit tenant settings, and
            # manage everything that's not a Sky-engineering action.
            # ``owner`` looks like the top role at first glance but in
            # this codebase it's a CREW role (pages/widgets/comments) and
            # explicitly cannot manage users (rbac_service.py, ADR-002).
            # If we ever rename roles, fix this script in lockstep.
            if existing is not None:
                existing.password_hash = get_password_hash(password)
                if not existing.role:
                    existing.role = "admin"
                existing.email_verified = True
                existing.has_completed_onboarding = True
                await session.commit()
                print(f"  [OK] tenant admin {email!r} refreshed (role={existing.role})")
            else:
                user = User(
                    email=email,
                    password_hash=get_password_hash(password),
                    name=name,
                    role="admin",
                    email_verified=True,
                    has_completed_onboarding=True,
                )
                session.add(user)
                await session.commit()
                print(f"  [OK] tenant admin {email!r} created (role=admin)")
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
