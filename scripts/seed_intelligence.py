import asyncio

from sqlalchemy import delete, select

from src.config.database import AsyncSessionLocal
from src.models.intelligence_signal import IntelligenceSignal
from src.models.planet import Planet


async def seed_intelligence():
    async with AsyncSessionLocal() as session:
        # Get all planets
        result = await session.execute(select(Planet))
        planets = result.scalars().all()

        if not planets:
            print("❌ No planets found. Please seed planets first.")
            return

        print(f"📡 Found {len(planets)} planets. Seeding signals for each...")

        for planet in planets:
            planet_id = planet.id
            print(f"🪐 Seeding signals for planet: {planet.name} ({planet_id})")

            # Clear existing signals for this planet
            await session.execute(
                delete(IntelligenceSignal).where(IntelligenceSignal.planet_id == planet_id)
            )

            signals = [
                IntelligenceSignal(
                    planet_id=planet_id,
                    category="now",
                    title="Gross margin dropped 4% this week",
                    content="Customer acquisition costs increased in Crew X, reducing overall profitability. Impact: If this trend continues, monthly margin may decline by ~6–8%.",
                    impact="Potential -6% to -8% monthly margin decline",
                    reason="High financial impact",
                    icon="TrendingDown",
                    color="red",
                    cta_label="Understand what changed | Simulate cost reduction",
                    chart_data={
                        "type": "line",
                        "series": [2400, 1398, 9800, 3908, 2800, 2400, 1300],
                        "labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                    },
                    confidence=0.92,
                ),
                IntelligenceSignal(
                    planet_id=planet_id,
                    category="smart",
                    title="Sales trend: Expansion potential",
                    content="Customers from Latin America sector are showing a 25% increase in engagement with Tier 2 products.",
                    impact="Estimated $45k additional ARR",
                    reason="Growth Opportunity",
                    icon="TrendingUp",
                    color="green",
                    cta_label="View Segment Details",
                    chart_data={
                        "type": "bar",
                        "series": [45, 52, 38, 65, 48, 72],
                        "labels": ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
                    },
                    confidence=0.88,
                ),
                IntelligenceSignal(
                    planet_id=planet_id,
                    category="explore",
                    title="Unusual churn in Segment B",
                    content="Detection of 3 enterprise accounts with usage drop > 40%.",
                    impact="$120k at risk",
                    reason="Churn Risk",
                    icon="Zap",
                    color="orange",
                    cta_label="Analyze Accounts",
                    chart_data={
                        "type": "area",
                        "series": [100, 95, 80, 82, 60, 42],
                        "labels": ["W1", "W2", "W3", "W4", "W5", "W6"],
                    },
                    confidence=0.85,
                ),
            ]

            session.add_all(signals)
            print(f"   ✅ Successfully seeded 3 intelligence signals for {planet.name}.")

        await session.commit()
        print("🚀 All planets seeded successfully!")


if __name__ == "__main__":
    asyncio.run(seed_intelligence())
