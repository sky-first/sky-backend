#!/usr/bin/env python3
"""
Script to verify dashboards table schema
"""

import asyncio
import os
from urllib.parse import unquote, urlparse

import asyncpg
from dotenv import load_dotenv

load_dotenv()


async def verify_schema():
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

    print("=== DASHBOARDS TABLE SCHEMA ===")
    cols = await conn.fetch(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns 
        WHERE table_name = 'dashboards' 
        ORDER BY ordinal_position;
    """
    )
    for row in cols:
        print(f"  {row['column_name']}: {row['data_type']} (nullable: {row['is_nullable']})")

    print("\n=== CHECKING FOR workspace_id ===")
    workspace_id_check = await conn.fetch(
        """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'dashboards' AND column_name = 'workspace_id';
    """
    )
    if workspace_id_check:
        print("  ❌ workspace_id STILL EXISTS!")
    else:
        print("  ✅ workspace_id does not exist (good)")

    print("\n=== CHECKING FOR planet_id ===")
    planet_id_check = await conn.fetch(
        """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'dashboards' AND column_name = 'planet_id';
    """
    )
    if planet_id_check:
        print("  ✅ planet_id EXISTS")
    else:
        print("  ❌ planet_id DOES NOT EXIST!")

    print("\n=== FOREIGN KEYS ===")
    fks = await conn.fetch(
        """
        SELECT
            tc.constraint_name,
            kcu.column_name,
            ccu.table_name AS foreign_table_name,
            ccu.column_name AS foreign_column_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
          ON tc.constraint_name = kcu.constraint_name
        JOIN information_schema.constraint_column_usage AS ccu
          ON ccu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_name = 'dashboards'
          AND kcu.column_name IN ('planet_id', 'workspace_id');
    """
    )
    for row in fks:
        print(f"  {row['column_name']} -> {row['foreign_table_name']}.{row['foreign_column_name']}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(verify_schema())
