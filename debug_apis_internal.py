import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from src.config.settings import settings
from src.services.enterprise_api_service import EnterpriseAPIService
from src.repositories.user import UserRepository


async def debug_apis():
    engine = create_async_engine(settings.DATABASE_URL)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        try:
            user_repo = UserRepository(db)
            # Get any user
            users = await user_repo.get_all(limit=1)
            if not users:
                print("No users found")
                return

            user = users[0]
            print(f"Testing for user: {user.email} ({user.id})")

            service = EnterpriseAPIService(db)
            apis = await service.list_apis(user)
            print(f"Successfully listed APIs: {len(apis)}")

        except Exception as e:
            print(f"ERROR: {type(e).__name__}: {str(e)}")
            import traceback

            traceback.print_exc()
        finally:
            await db.close()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(debug_apis())
