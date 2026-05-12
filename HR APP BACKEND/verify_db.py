import asyncio
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import JobDescription

async def verify():
    async with AsyncSessionLocal() as session:
        query = select(JobDescription)
        jobs = (await session.execute(query)).scalars().all()
        print("\n--- Current Job Descriptions ---")
        for j in jobs:
            print(f"ID: {j.id}, Title: {j.title}, Exp Max: {j.experience_max}")
        print("-------------------------------\n")

if __name__ == "__main__":
    asyncio.run(verify())
