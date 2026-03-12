import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from src.config.settings import settings

async def check_table():
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.connect() as conn:
        try:
            result = await conn.execute(text("SELECT count(*) FROM enterprise_apis"))
            count = result.scalar()
            print(f"Table enterprise_apis exists. Count: {count}")
        except Exception as e:
            print(f"Table error: {str(e)}")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(check_table())
