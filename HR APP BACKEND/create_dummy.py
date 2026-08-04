import asyncio
import sys
import os

# Add the current directory to sys.path to find the 'app' package
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.models import User, UserRole
from app.services.auth_service import hash_password

# Database URL (SQLite)
DATABASE_URL = "sqlite+aiosqlite:///d:/shubham/HR APP/Backend/hr_platform.db"

async def create_dummy_data():
    engine = create_async_engine(DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Create Dummy Candidate
        result = await session.execute(select(User).where(User.email == "[email-redacted]"))
        user = result.scalars().first()
        if not user:
            user = User(
                email="[email-redacted]",
                full_name="Demo Candidate",
                role=UserRole.candidate,
                hashed_password=hash_password("password123"),
                is_active=True
            )
            session.add(user)
            print("Created dummy candidate: [email-redacted] / password123")
        
        # Create Dummy HR
        result = await session.execute(select(User).where(User.email == "[email-redacted]"))
        hr_user = result.scalars().first()
        if not hr_user:
            hr_user = User(
                email="[email-redacted]",
                full_name="Demo HR",
                role=UserRole.hr,
                hashed_password=hash_password("password123"),
                is_active=True
            )
            session.add(hr_user)
            print("Created dummy HR: [email-redacted] / password123")
            
        await session.commit()

if __name__ == "__main__":
    asyncio.run(create_dummy_data())
