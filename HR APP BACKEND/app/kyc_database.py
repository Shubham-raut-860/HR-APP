import logging
import asyncio
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)
_kyc_schema_ready = False
_kyc_schema_lock = asyncio.Lock()


class KycBase(DeclarativeBase):
    pass


_kyc_engine = create_async_engine(
    settings.KYC_DATABASE_URL,
    future=True,
    pool_pre_ping=True,
)

KycSessionLocal = async_sessionmaker(
    _kyc_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_kyc_db() -> AsyncGenerator[AsyncSession, None]:
    await ensure_kyc_schema_ready()
    async with KycSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def create_kyc_tables() -> None:
    import app.kyc_models  # noqa: F401

    async with _kyc_engine.begin() as conn:
        await conn.run_sync(KycBase.metadata.create_all)


async def ensure_kyc_schema_ready() -> None:
    global _kyc_schema_ready
    if _kyc_schema_ready:
        return
    async with _kyc_schema_lock:
        if _kyc_schema_ready:
            return
        await create_kyc_tables()
        _kyc_schema_ready = True
