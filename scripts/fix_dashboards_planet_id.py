#!/usr/bin/env python3
"""
Script to fix dashboards.planet_id column migration
This script renames workspace_id to planet_id in the dashboards table
"""

import asyncio
import os
from urllib.parse import unquote, urlparse

import asyncpg
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


async def fix_dashboards_planet_id():
    # Get database URL from environment
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:password@localhost:5433/ai_saas_db",
    )

    # Parse the URL to extract connection details
    # Remove the +asyncpg part if present
    db_url = database_url.replace("+asyncpg", "")
    parsed = urlparse(db_url)

    # Extract connection details
    user = parsed.username or "postgres"
    password = unquote(parsed.password or "")  # URL decode password
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    database = parsed.path.lstrip("/") or "ai_saas_db"

    print(f"Connecting to database: {host}:{port}/{database}")

    try:
        # Connect to database
        conn = await asyncpg.connect(
            host=host, port=port, user=user, password=password, database=database
        )

        print("Connected successfully!")

        # Check if workspace_id column exists
        check_query = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'dashboards'
        AND column_name IN ('workspace_id', 'planet_id');
        """

        columns = await conn.fetch(check_query)
        column_names = [row["column_name"] for row in columns]

        print(f"Found columns in dashboards table: {column_names}")

        if "planet_id" in column_names:
            print("✅ Column planet_id already exists. No changes needed.")
        elif "workspace_id" in column_names:
            print("🔄 Renaming workspace_id to planet_id...")

            # Start transaction
            async with conn.transaction():
                # Rename the column
                await conn.execute(
                    """
                    ALTER TABLE dashboards
                    RENAME COLUMN workspace_id TO planet_id;
                """
                )

                # Drop old index if exists
                try:
                    await conn.execute(
                        """
                        DROP INDEX IF EXISTS idx_dashboards_workspace_id;
                    """
                    )
                except Exception as e:
                    print(f"Note: Could not drop old index (may not exist): {e}")

                # Create new index
                await conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_dashboards_planet_id
                    ON dashboards(planet_id)
                    WHERE deleted_at IS NULL;
                """
                )

                # Drop old foreign key constraint if exists
                try:
                    await conn.execute(
                        """
                        ALTER TABLE dashboards
                        DROP CONSTRAINT IF EXISTS dashboards_workspace_id_fkey;
                    """
                    )
                except Exception as e:
                    print(f"Note: Could not drop old FK (may not exist): {e}")

                # Create new foreign key constraint
                await conn.execute(
                    """
                    ALTER TABLE dashboards
                    ADD CONSTRAINT dashboards_planet_id_fkey
                    FOREIGN KEY (planet_id)
                    REFERENCES planets(id)
                    ON DELETE CASCADE;
                """
                )

            print("✅ Successfully renamed workspace_id to planet_id!")
        else:
            print(
                "❌ Neither workspace_id nor planet_id found. Table may not exist or have different structure."
            )
            # Check if table exists
            table_check = await conn.fetch(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'dashboards'
                );
            """
            )
            if table_check[0]["exists"]:
                # Get all columns
                all_columns = await conn.fetch(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'dashboards';
                """
                )
                print(f"Available columns: {[row['column_name'] for row in all_columns]}")
            else:
                print("Table 'dashboards' does not exist.")

        await conn.close()
        print("✅ Done!")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        raise


if __name__ == "__main__":
    asyncio.run(fix_dashboards_planet_id())
