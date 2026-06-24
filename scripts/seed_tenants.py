"""Seed two demo tenants into the platform's ``tenant_registry``.

Use for local end-to-end validation of Projeto A. Two tenants get
inserted (or upserted) — ``alpha`` and ``beta`` — both pointing at
local Postgres databases that exist alongside the platform DB:

* ``tenant_alpha`` (Postgres database on the same container)
* ``tenant_beta``

Run from the backend repo root:

    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db \\
    venv/Scripts/python.exe scripts/seed_tenants.py

The script is idempotent: re-running it updates the registry rows in
place. ``--remove`` drops the two rows (the underlying tenant DBs are
left untouched).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from typing import Iterable

# Make ``src.*`` importable when running as ``python scripts/seed_tenants.py``.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from src.config.database import AsyncSessionLocal  # noqa: E402
from src.models.tenant import Tenant  # noqa: E402


# ``alpha`` and ``beta`` mirror the pair used by Phase 2 PR #4's
# integration fixture, so the names line up across the test suite and
# the smoke script.
SEED_TENANTS: list[dict] = [
    {
        "slug": "alpha",
        "display_name": "Alpha Demo Tenant",
        "tier": "pilot",
        "db_host": "localhost",
        "db_port": 5432,
        "db_name": "tenant_alpha",
        # No Secrets Manager arn in local dev — manager falls back to
        # POSTGRES_USER / POSTGRES_PASSWORD env vars.
        "db_credentials_secret_arn": "local-dev:tenant_alpha",
        "redis_host": "localhost",
        "redis_credentials_secret_arn": "local-dev:tenant_alpha",
        "sso_provider": "google",
        "sso_config": {},
    },
    {
        "slug": "beta",
        "display_name": "Beta Demo Tenant",
        "tier": "foundation",
        "db_host": "localhost",
        "db_port": 5432,
        "db_name": "tenant_beta",
        "db_credentials_secret_arn": "local-dev:tenant_beta",
        "redis_host": "localhost",
        "redis_credentials_secret_arn": "local-dev:tenant_beta",
        "sso_provider": "google",
        "sso_config": {},
    },
]


async def upsert_one(session: AsyncSession, payload: dict) -> Tenant:
    existing = (
        await session.execute(select(Tenant).where(Tenant.slug == payload["slug"]))
    ).scalar_one_or_none()

    if existing is not None:
        for key, value in payload.items():
            setattr(existing, key, value)
        return existing

    tenant = Tenant(id=uuid.uuid4(), **payload)
    session.add(tenant)
    return tenant


async def remove_one(session: AsyncSession, slug: str) -> bool:
    existing = (
        await session.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if existing is None:
        return False
    await session.delete(existing)
    return True


async def main(action: str, slugs: Iterable[str]) -> None:
    async with AsyncSessionLocal() as session:
        if action == "seed":
            for payload in SEED_TENANTS:
                if slugs and payload["slug"] not in slugs:
                    continue
                tenant = await upsert_one(session, payload)
                print(f"  [seed] {tenant.slug}  tier={tenant.tier}  " f"db={tenant.db_name}")
        elif action == "remove":
            for payload in SEED_TENANTS:
                if slugs and payload["slug"] not in slugs:
                    continue
                removed = await remove_one(session, payload["slug"])
                marker = "removed" if removed else "not present"
                print(f"  [remove] {payload['slug']}  ({marker})")
        await session.commit()

    print("done.")


def _cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        nargs="?",
        choices=["seed", "remove"],
        default="seed",
    )
    parser.add_argument(
        "--slug",
        action="append",
        default=[],
        help="Limit to this slug (repeatable). Default: all SEED_TENANTS.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.action, slugs=args.slug))


if __name__ == "__main__":
    _cli()
