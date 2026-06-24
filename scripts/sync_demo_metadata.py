#!/usr/bin/env python3
"""One-off: force metadata sync for demo connections.

The original `seed_demo_connections.py` wraps `sync_connection` in a silent
try/except — useful in CI but it hides the real failure when the demo
Postgres host is unreachable, the credentials are wrong, or the schema is
empty. This script does the same sync work but lets every exception bubble
up with a full traceback so we can see why metadata never landed.
"""
from __future__ import annotations

import asyncio
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if not os.environ.get("DATABASE_URL"):
    print("Set DATABASE_URL first (source .env.local).", file=sys.stderr)
    sys.exit(1)

from sqlalchemy import select  # noqa: E402

from src.config.database import AsyncSessionLocal  # noqa: E402
from src.models.user import User  # noqa: E402
from src.models.connection import DataConnection  # noqa: E402
from src.services.connection_service import ConnectionService  # noqa: E402

OWNER_EMAIL = "rbac.owner@example.com"


async def main() -> None:
    async with AsyncSessionLocal() as db:
        owner = (await db.execute(select(User).where(User.email == OWNER_EMAIL))).scalar_one()
        rows = (
            (
                await db.execute(
                    select(DataConnection).where(
                        DataConnection.name.like("Demo —%"),
                        DataConnection.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        ids = [(c.id, c.name, c.status) for c in rows]

    print(f"Found {len(ids)} demo connections")
    for cid, name, status in ids:
        print(f"  • {name} (id={cid}, status={status})")
    print()

    successes = 0
    failures = 0
    for cid, name, _status in ids:
        print(f"=== Syncing {name} ({cid}) ===")
        try:
            async with AsyncSessionLocal() as db2:
                svc = ConnectionService(db2)
                resp = await svc.sync_connection(cid, owner)
                print(f"  ✓ OK — tables={getattr(resp, 'tables_count', '?')}")
                successes += 1
        except Exception as exc:
            failures += 1
            print(f"  ✗ FAILED: {type(exc).__name__}: {exc}")
            traceback.print_exc()
        print()

    print(f"\n{successes} succeeded, {failures} failed")


if __name__ == "__main__":
    asyncio.run(main())
