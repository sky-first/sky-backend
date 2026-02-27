import sys
import os
import asyncio
from sqlalchemy import select

# Add project root to sys.path
sys.path.append(os.path.abspath("src"))

from src.config.database import AsyncSessionLocal
from src.models.space import Space
from src.repositories.space import SpaceTableRepository
from src.services.space_service import SpaceService
from src.models.user import User

async def check_finance_tables():
    async with AsyncSessionLocal() as db:
        # 1. Find Finance space
        result = await db.execute(select(Space).where(Space.name == "Finance"))
        space = result.scalar_one_or_none()
        if not space:
            print("Finance space not found")
            return

        print(f"Space: {space.name} ({space.id})")
        
        # 2. Find any user (since we need it for SpaceService)
        user_result = await db.execute(select(User).limit(1))
        user = user_result.scalar_one_or_none()
        if not user:
            print("No users found in database")
            return
        
        # Override user.id to match space.created_by to avoid ForbiddenError 
        # in this debug script, or just adjust the script to use creator
        creator_result = await db.execute(select(User).where(User.id == space.created_by))
        creator = creator_result.scalar_one_or_none()
        if creator:
            user = creator
        
        print(f"User: {user.name} ({user.id})")

        # 3. Call SpaceService.get_space_tables
        space_service = SpaceService(db)
        try:
            tables = await space_service.get_space_tables(space.id, user)
            
            print(f"Total tables returned by SpaceService: {len(tables)}")
            selected_tables = [t for t in tables if t.get("selected")]
            print(f"Selected tables: {len(selected_tables)}")
            for t in selected_tables:
                print(f"  - {t.get('connection_name')}: {t.get('schema_name')}.{t.get('table_name')}")
        except Exception as e:
            print(f"Error calling get_space_tables: {e}")

        # 4. Check raw space_tables
        st_repo = SpaceTableRepository(db)
        raw_tables = await st_repo.get_space_tables(space.id)
        print(f"Raw space_tables count: {len(raw_tables)}")
        for rt in raw_tables:
            print(f"  - Conn: {rt.connection_id}, Table: {rt.schema_name or 'None'}.{rt.table_name}")

if __name__ == "__main__":
    asyncio.run(check_finance_tables())
