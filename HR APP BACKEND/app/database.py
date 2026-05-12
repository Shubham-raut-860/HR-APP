import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import inspect as sa_inspect
from app.config import settings

logger = logging.getLogger(__name__)

# FIX [DB-1]: Added pool configuration for PostgreSQL production use.
# pool_pre_ping=True: validates connections before use, preventing stale
# connection errors ("SSL SYSCALL error: EOF") after idle periods.
# pool_size / max_overflow / pool_recycle are PostgreSQL-only — SQLite
# auto-selects NullPool and ignores these safely.
_engine_kwargs: dict = {
    # "debug" restricts SQL echo to Python's DEBUG log level, preventing
    # PII (emails, hashed passwords in WHERE clauses) from being shipped
    # to centralized log aggregators that typically capture INFO and above.
    "echo": "debug" if settings.APP_ENV == "development" else False,
    "future": True,
    "pool_pre_ping": True,
}

if not settings.DATABASE_URL.startswith("sqlite"):
    _engine_kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
        "pool_timeout": 30,
        "pool_recycle": 1800,  # Recycle every 30 min to avoid stale connections
    })

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def commit_db(db: AsyncSession) -> None:
    await db.commit()

async def create_tables():
    """
    Development-only helper to create missing tables via SQLAlchemy metadata.

    IMPORTANT:
    - Application startup no longer calls this helper.
    - Runtime schema management is handled by Alembic migrations.
    - create_all() does not perform ALTERs and must not be used as a
      production migration mechanism.
    """
    import app.models  # BUG FIX: Force load models into metadata
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # ── Schema drift check ──────────────────────────────────────────────
    # BUG-11 FIX: permanently commented out = no startup warning when columns
    # are missing after a skipped migration. Re-enabled with a non-fatal guard
    # so a transient DB error at boot does NOT prevent the app from starting.
    try:
        await _check_schema_drift()
    except Exception as _drift_err:
        logger.warning("Schema drift check failed (non-fatal): %s", _drift_err)


async def _check_schema_drift():
    """Compare ORM metadata against the live DB schema and warn about drift.

    Checks for:
    - Tables defined in models but missing from the database.
    - Columns defined in models but missing from existing tables.

    This is a best-effort check — it does NOT detect type changes or
    constraint differences. Use Alembic for full migration management.
    """
    async with engine.connect() as conn:
        def _inspect_sync(sync_conn):
            inspector = sa_inspect(sync_conn)
            db_tables = set(inspector.get_table_names())
            expected_tables = set(Base.metadata.tables.keys())

            missing_tables = expected_tables - db_tables
            for t in sorted(missing_tables):
                logger.warning(
                    "Schema drift: table '%s' is defined in models but "
                    "missing from the database. Run migrations.", t)

            # For tables that DO exist, check for missing columns.
            for table_name in sorted(expected_tables & db_tables):
                db_columns = {
                    col["name"] for col in inspector.get_columns(table_name)
                }
                model_columns = {
                    col.name
                    for col in Base.metadata.tables[table_name].columns
                }
                missing_cols = model_columns - db_columns
                for col in sorted(missing_cols):
                    logger.warning(
                        "Schema drift: column '%s.%s' is defined in models "
                        "but missing from the database. Run migrations.",
                        table_name, col)

        await conn.run_sync(_inspect_sync)


