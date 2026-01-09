#!/usr/bin/env python3
"""
Script to fix dashboards.is_locked column type from String to Boolean
"""

import asyncio
import os
from urllib.parse import unquote, urlparse

import asyncpg
from dotenv import load_dotenv

load_dotenv()


async def fix_is_locked():
    database_url = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost:5433/ai_saas_db"
    )
    db_url = database_url.replace("+asyncpg", "")
    parsed = urlparse(db_url)
    password = unquote(parsed.password or "")

    conn = await asyncpg.connect(
        host=parsed.hostname or "localhost",
        port=parsed.port or 5432,
        user=parsed.username or "postgres",
        password=password,
        database=parsed.path.lstrip("/") or "ai_saas_db",
    )

    print("=== CHECKING is_locked COLUMN TYPE ===")
    col_info = await conn.fetch(
        """
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'dashboards' AND column_name = 'is_locked';
    """
    )

    if not col_info:
        print("❌ Column is_locked not found!")
        await conn.close()
        return

    current_type = col_info[0]["data_type"]
    print(f"Current type: {current_type}")

    if current_type == "boolean":
        print("✅ Column is already Boolean. No changes needed.")
    elif current_type in ("character varying", "varchar", "text"):
        print("🔄 Converting String to Boolean...")

        async with conn.transaction():
            # First, remove the default
            await conn.execute(
                """
                ALTER TABLE dashboards 
                ALTER COLUMN is_locked DROP DEFAULT;
            """
            )

            # Update existing string values to boolean
            await conn.execute(
                """
                UPDATE dashboards 
                SET is_locked = CASE 
                    WHEN is_locked IN ('true', 'True', '1', 'yes') THEN true
                    ELSE false
                END;
            """
            )

            # Change column type to boolean
            await conn.execute(
                """
                ALTER TABLE dashboards 
                ALTER COLUMN is_locked TYPE boolean 
                USING is_locked::boolean;
            """
            )

            # Set new default
            await conn.execute(
                """
                ALTER TABLE dashboards 
                ALTER COLUMN is_locked SET DEFAULT false;
            """
            )

            # Ensure NOT NULL
            await conn.execute(
                """
                ALTER TABLE dashboards 
                ALTER COLUMN is_locked SET NOT NULL;
            """
            )

        print("✅ Successfully converted is_locked to Boolean!")
    else:
        print(f"⚠️  Unexpected type: {current_type}. Manual intervention may be needed.")

    await conn.close()
    print("✅ Done!")


if __name__ == "__main__":
    asyncio.run(fix_is_locked())
