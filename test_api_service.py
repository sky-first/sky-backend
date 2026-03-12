import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from src.config.settings import settings
from src.services.enterprise_api_service import EnterpriseAPIService
from src.models.user import User
import uuid

async def test_service():
    engine = create_async_engine(settings.DATABASE_URL)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with AsyncSessionLocal() as db:
        service = EnterpriseAPIService(db)
        # Create a mock user
        mock_user = User(id=uuid.uuid4()) 
        
        print("Testing list_apis...")
        try:
            apis = await service.list_apis(mock_user)
            print(f"List APIs successful: {len(apis)} found")
        except Exception as e:
            print(f"List APIs failed: {str(e)}")
            import traceback
            traceback.print_exc()

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(test_service())
