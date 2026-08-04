"""
One-time script to create default pages for all users who don't have one.
Works whether the table is called 'pages' or 'planets'.
Run from the sky-poc-backend directory with the venv activated:
  python scripts/ensure-default-pages.py
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.config.settings import settings


async def main():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # 1. Detect which table name is in use
        result = await db.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN ('pages','planets')"
            )
        )
        tables = [row[0] for row in result.fetchall()]
        print(f"Tables found: {tables}")

        if "pages" in tables:
            page_table = "pages"
            member_table = "page_members"
        elif "planets" in tables:
            page_table = "planets"
            member_table = "planet_members"
        else:
            print("ERROR: Neither 'pages' nor 'planets' table found!")
            return

        print(f"Using table: {page_table}")

        # 2. Get all users
        result = await db.execute(text("SELECT id, name, email FROM users ORDER BY created_at"))
        users = result.fetchall()
        print(f"Found {len(users)} users\n")

        for user_id, user_name, user_email in users:
            # Check if user already has a page
            result = await db.execute(
                text(
                    f"SELECT COUNT(*) FROM {page_table} WHERE owner_id = :uid AND deleted_at IS NULL"
                ),
                {"uid": user_id},
            )
            count = result.scalar()

            if count and count > 0:
                print(f"  [ok] {user_email} - already has {count} page(s), skipping")
                continue

            # Create default page
            page_id = uuid.uuid4()
            first_name = (user_name or "").split(" ")[0] if user_name else ""
            page_name = f"{first_name}'s Universe" if first_name else "My Universe"
            now = datetime.now(timezone.utc)

            await db.execute(
                text(
                    f"""
                INSERT INTO {page_table}
                    (id, name, description, type, color, icon, owner_id, is_active, created_at, updated_at)
                VALUES
                    (:id, :name, :desc, 'personal', '#3B82F6', NULL, :owner, true, :now, :now)
            """
                ),
                {
                    "id": page_id,
                    "name": page_name,
                    "desc": "Your first universe",
                    "owner": user_id,
                    "now": now,
                },
            )

            # Add owner as member
            await db.execute(
                text(
                    f"""
                INSERT INTO {member_table}
                    (id, {page_table[:-1]}_id, user_id, role, created_at)
                VALUES
                    (:id, :page_id, :user_id, 'owner', :now)
            """
                ),
                {
                    "id": uuid.uuid4(),
                    "page_id": page_id,
                    "user_id": user_id,
                    "now": now,
                },
            )

            await db.commit()
            print(f"  [created] {user_email} - created page '{page_name}'")

        print("\nDone.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
