#!/usr/bin/env python3
"""Promote the default test user (test@example.com) to admin.

This is meant for dev/staging environments to quickly unlock Admin UI testing.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path (so `src.*` imports work)
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, update  # noqa: E402

from src.config.database import AsyncSessionLocal, engine  # noqa: E402
from src.models.planet import Planet  # noqa: F401, E402
from src.models.user import User  # noqa: E402

# Import related models to register relationships (avoid mapper lookup errors)
from src.models.workspace import Workspace  # noqa: F401, E402

TEST_EMAIL = os.getenv("TEST_EMAIL", "test@example.com")


async def promote_test_user():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == TEST_EMAIL))
        user = result.scalar_one_or_none()

        if not user:
            print(f"❌ User not found: {TEST_EMAIL}")
            return 1

        if user.role == "admin":
            print(f"✅ {TEST_EMAIL} is already admin.")
            return 0

        await session.execute(update(User).where(User.email == TEST_EMAIL).values(role="admin"))
        await session.commit()

        print(f"✅ Promoted {TEST_EMAIL} to role=admin")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(promote_test_user()))
