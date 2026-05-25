#!/usr/bin/env python3
"""Regenerate /tmp/rbac-tokens.json with fresh JWTs for every seeded
RBAC persona. Used by scripts/playwright-rbac-validate.ts in the
frontend repo to drive headless visual checks.

Local development only — signs against the BE's own JWT secret.
"""

import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.core.security import create_access_token, create_refresh_token
from src.models.user import User

PERSONAS = [
    "rbac.viewer-crewowner@example.com",
    "rbac.crew-only-editor@example.com",
    "rbac.multi-crew@example.com",
    "rbac.member-spaceowner@example.com",
    "rbac.demo@example.com",
    "rbac.member-viewer@example.com",
    # Phase 4 baseline platform admin (sees all settings panels)
    "rbac.admin@example.com",
]

OUT_PATH = Path("/tmp/rbac-tokens.json")


async def main() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    out: dict[str, dict[str, str]] = {}
    async with Session() as session:
        for email in PERSONAS:
            user = (
                await session.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            if user is None:
                print(f"  ! {email} missing — skipping", file=sys.stderr)
                continue
            data = {"sub": str(user.id), "email": user.email, "role": user.role}
            access = create_access_token(data, expires_delta=timedelta(hours=12))
            refresh = create_refresh_token(data)
            out[email] = {
                "access": access,
                "refresh": refresh,
                "user_id": str(user.id),
                "platform_role": user.role or "member",
            }
            print(f"  ✓ {email}  (role={user.role})")

    OUT_PATH.write_text(json.dumps(out, indent=2))
    print(f"\n  → {len(out)} tokens written to {OUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
