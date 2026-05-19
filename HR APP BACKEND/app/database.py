import logging
import os
from typing import AsyncGenerator

from sqlalchemy import event, inspect as sa_inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)


def _is_sqlite_url(database_url: str) -> bool:
    return (database_url or "").strip().lower().startswith("sqlite")


def _is_postgres_url(database_url: str) -> bool:
    lower = (database_url or "").strip().lower()
    return lower.startswith("postgresql") or lower.startswith("postgres://")


# FIX [DB-1]: Added pool configuration for PostgreSQL production use.
# pool_pre_ping=True: validates connections before use, preventing stale
# connection errors ("SSL SYSCALL error: EOF") after idle periods.
_sql_echo_raw = (os.getenv("SQLALCHEMY_ECHO") or "").strip().lower()
_sql_echo_enabled = _sql_echo_raw in {"1", "true", "yes", "on"}
_engine_kwargs: dict = {
    "echo": _sql_echo_enabled,
    "future": True,
    "pool_pre_ping": True,
}

# Force SQL statement logger quiet unless explicit echo is enabled.
if not _sql_echo_enabled:
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

# BUG-08 FIX: URL detection must be case-insensitive (e.g., SQLITE://...).
if not _is_sqlite_url(settings.DATABASE_URL):
    _engine_kwargs.update(
        {
            "pool_size": 10,
            "max_overflow": 20,
            "pool_timeout": 30,
            "pool_recycle": 1800,  # Recycle every 30 min to avoid stale connections
        }
    )

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


_register_pgvector_async = None
if _is_postgres_url(settings.DATABASE_URL):
    try:
        from pgvector.asyncpg import register_vector as _register_pgvector_async  # type: ignore[assignment]
    except ImportError:
        _register_pgvector_async = None


if _register_pgvector_async is not None:
    @event.listens_for(engine.sync_engine, "connect")
    def _register_pgvector_on_connect(dbapi_connection, connection_record) -> None:
        dbapi_connection.run_async(_register_pgvector_async)
        connection_record.info["pgvector_registered"] = True


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def commit_db(db: AsyncSession) -> None:
    await db.commit()


async def verify_pgvector_registration(db_engine: AsyncEngine | None = None) -> None:
    """Validate pgvector extension + asyncpg codec setup for PostgreSQL."""
    if not _is_postgres_url(settings.DATABASE_URL):
        return

    if _register_pgvector_async is None:
        raise RuntimeError(
            "pgvector asyncpg registration is unavailable for PostgreSQL. "
            "Install the 'pgvector' Python package."
        )

    target_engine = db_engine or engine
    async with target_engine.connect() as conn:
        extension_present = (
            await conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            )
        ).scalar_one_or_none()
        if extension_present is None:
            raise RuntimeError(
                "PostgreSQL extension 'vector' is not installed. "
                "Run: CREATE EXTENSION IF NOT EXISTS vector;"
            )

        # Codec probe: bind text and cast it to vector so driver adaptation is exercised.
        dim = int(settings.EMBEDDING_DIM)
        probe = "[" + ",".join("0" for _ in range(dim)) + "]"
        await conn.execute(text("SELECT CAST(:probe AS vector)"), {"probe": probe})


async def create_tables() -> None:
    """
    Development-only helper to create missing tables via SQLAlchemy metadata.

    IMPORTANT:
    - Application startup no longer calls this helper.
    - Runtime schema management is handled by Alembic migrations.
    - create_all() does not perform ALTERs and must not be used as a
      production migration mechanism.
    """
    if str(getattr(settings, "APP_ENV", "")).lower() == "production":
        raise RuntimeError(
            "create_tables() must not be called in production; use Alembic migrations."
        )

    import app.models  # noqa: F401  # Force load models into metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Keep drift checks here for local tooling convenience only.
    try:
        await _check_schema_drift(engine)
    except Exception as drift_err:
        logger.warning("schema_drift_check_failed non_fatal=true error=%s", drift_err)


async def _check_schema_drift(db_engine: AsyncEngine | None = None) -> None:
    """Compare ORM metadata against the live DB schema and log non-fatal drift warnings."""
    target_engine = db_engine or engine
    async with target_engine.connect() as conn:
        def _inspect_sync(sync_conn) -> None:
            inspector = sa_inspect(sync_conn)
            db_tables = set(inspector.get_table_names())
            expected_tables = set(Base.metadata.tables.keys())

            missing_tables = expected_tables - db_tables
            for table_name in sorted(missing_tables):
                logger.warning(
                    "schema_drift_detected type=missing_table table=%s action=run_migrations",
                    table_name,
                )

            for table_name in sorted(expected_tables & db_tables):
                db_columns = {col["name"] for col in inspector.get_columns(table_name)}
                model_columns = {
                    col.name for col in Base.metadata.tables[table_name].columns
                }
                missing_cols = model_columns - db_columns
                for col_name in sorted(missing_cols):
                    logger.warning(
                        "schema_drift_detected type=missing_column table=%s column=%s action=run_migrations",
                        table_name,
                        col_name,
                    )

        await conn.run_sync(_inspect_sync)

