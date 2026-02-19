import asyncio
import os
import sys

# Add src to path
sys.path.append(os.getcwd())

# Setup DB connection
from src.config.database import AsyncSessionLocal
from sqlalchemy.future import select
from sqlalchemy import desc
from src.models.dashboard import Widget


async def check_latest_widget():
    async with AsyncSessionLocal() as db:
        # Get latest widget
        stmt = select(Widget).order_by(desc(Widget.created_at)).limit(1)
        result = await db.execute(stmt)
        widget = result.scalar_one_or_none()

        if widget:
            print(f"Widget ID: {widget.id}")
            print(f"Type: {widget.type}")
            print(f"Title: {widget.title}")

            data = widget.data or {}
            print(f"Infographic Data Present: {'infographic_data' in data}")

            if "infographic_data" in data:
                print(f"Infographic Data Keys: {list(data['infographic_data'].keys())}")
                print(f"Infographic Title: {data['infographic_data'].get('title')}")
            else:
                print(f"Data Keys: {list(data.keys())}")
        else:
            print("No widgets found.")


if __name__ == "__main__":
    asyncio.run(check_latest_widget())
