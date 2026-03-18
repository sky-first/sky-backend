import asyncio
import os
import sys

# Add current directory to path
sys.path.append(os.getcwd())

from sqlalchemy import select

from src.config.database import AsyncSessionLocal
from src.models.connection import ConnectionMetadata
from src.models.space import Space, SpaceConnection, SpaceTable


async def check_data():
    async with AsyncSessionLocal() as db:
        # Check spaces
        result = await db.execute(select(Space))
        spaces = result.scalars().all()
        print(f"Total Spaces: {len(spaces)}")
        for s in spaces:
            print(f"Space: {s.name} ({s.id})")

            # Check connections for this space
            res_conn = await db.execute(
                select(SpaceConnection).where(SpaceConnection.space_id == s.id)
            )
            conns = res_conn.scalars().all()
            print(f"  Connections: {len(conns)}")
            for c in conns:
                print(f"    Connection ID: {c.connection_id}")

                # Check metadata
                res_meta = await db.execute(
                    select(ConnectionMetadata).where(
                        ConnectionMetadata.connection_id == c.connection_id
                    )
                )
                meta = res_meta.scalar_one_or_none()
                if meta:
                    tables = meta.tables or []
                    print(f"      Metadata found: {len(tables)} tables")
                    if len(tables) > 0:
                        print(f"      First table example: {tables[0]}")
                else:
                    print("      No metadata found")

            # Check selected tables
            res_tabs = await db.execute(
                select(SpaceTable).where(SpaceTable.space_id == s.id)
            )
            tabs = res_tabs.scalars().all()
            print(f"  Selected Tables: {len(tabs)}")


if __name__ == "__main__":
    asyncio.run(check_data())
