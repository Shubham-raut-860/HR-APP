import asyncio
from sqlalchemy import select, update
from app.database import AsyncSessionLocal
from app.models import JobDescription

async def sanitize_experience_max():
    async with AsyncSessionLocal() as session:
        # Update all JobDescriptions where experience_max is 99 to 10
        query = update(JobDescription).where(JobDescription.experience_max == 99).values(experience_max=10)
        result = await session.execute(query)
        await session.commit()
        print(f"Updated {result.rowcount} job descriptions (99 -> 10).")

        # Also double check for any other anomalies
        query_all = select(JobDescription)
        jobs = (await session.execute(query_all)).scalars().all()
        for job in jobs:
            if job.experience_max > 20 and job.experience_max != 99:
                 # Clamp any other unusually high values just in case
                 job.experience_max = 10
        await session.commit()
        print("Final sanity check and clamping complete.")

if __name__ == "__main__":
    asyncio.run(sanitize_experience_max())
