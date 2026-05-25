#!/usr/bin/env python3
"""List all users and optionally promote one to admin."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, update, text
from src.config.database import AsyncSessionLocal, engine
from src.models.page import Page  # noqa: F401
from src.models.user import User
from src.models.workspace import Workspace  # noqa: F401

TARGET_EMAIL = os.getenv("TARGET_EMAIL", "").strip()


async def run():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT email, role, created_at FROM users ORDER BY created_at DESC LIMIT 20")
        )
        rows = result.fetchall()
        print("\n=== Users in database ===")
        for row in rows:
            print(f"  {row.email}  |  role={row.role}  |  created={str(row.created_at)[:19]}")
        print("=========================\n")

        if TARGET_EMAIL:
            result2 = await session.execute(select(User).where(User.email == TARGET_EMAIL))
            user = result2.scalar_one_or_none()
            if not user:
                print(f"❌ User not found: {TARGET_EMAIL}")
            elif user.role == "admin":
                print(f"✅ {TARGET_EMAIL} is already admin.")
            else:
                await session.execute(update(User).where(User.email == TARGET_EMAIL).values(role="admin"))
                await session.commit()
                print(f"✅ Promoted {TARGET_EMAIL} to admin!")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
