"""
migrate_all.py — Single unified migration for Jobora
======================================================
Replaces all individual migration files:
  • migrate.py
  • run_migrations.py
  • add_archive_salary_migration.py
  • add_career_breaks_migration.py
  • add_education_requirement_migration.py
  • add_file_hash_migration.py
  • add_job_id_index_migration.py
  • add_scoring_v2_migration.py
  • add_location_and_created_at_index_migration.py  (Bug 2 + Bug 7 fixes)

Usage:
    cd backend
    python migrate_all.py

Safe to run multiple times — every step checks for existence before applying.
Supports SQLite (dev) and PostgreSQL (staging / production) via DATABASE_URL.
"""

import asyncio
import logging
import os
import sys

def _find_backend_root() -> str:
    """Walk up from the script location to find the folder containing app/__init__.py.
    Works whether the script is run from inside a subfolder or directly from Backend/."""
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        if os.path.isfile(os.path.join(current, "app", "__init__.py")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, _find_backend_root())

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("migrate_all")

# ─── Dialect helpers ──────────────────────────────────────────────────────────


async def column_exists(conn, table: str, col: str, dialect: str) -> bool:
    if dialect == "sqlite":
        r = await conn.execute(text(f"PRAGMA table_info({table})"))
        return col in [row[1] for row in r.fetchall()]
    r = await conn.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": col},
    )
    return bool(r.scalar())


async def index_exists(conn, index_name: str, table: str, dialect: str) -> bool:
    if dialect == "sqlite":
        r = await conn.execute(
            text("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name=:n"),
            {"n": index_name},
        )
        return bool(r.scalar())
    if dialect == "postgresql":
        r = await conn.execute(
            text("SELECT COUNT(*) FROM pg_indexes WHERE indexname=:n"),
            {"n": index_name},
        )
        return bool(r.scalar())
    # MySQL / MariaDB
    r = await conn.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.statistics "
            "WHERE table_name=:t AND index_name=:n"
        ),
        {"t": table, "n": index_name},
    )
    return bool(r.scalar())


async def add_column(conn, table: str, col: str, col_type: str, dialect: str) -> None:
    if await column_exists(conn, table, col, dialect):
        log.info("  ✅ %-30s already exists — skipped", f"{table}.{col}")
        return
    # PostgreSQL supports IF NOT EXISTS; SQLite / MySQL do not — we guard above.
    await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
    log.info("  ✅ %-30s ADDED", f"{table}.{col}")


async def add_index(
    conn,
    index_name: str,
    table: str,
    columns_expr: str,
    dialect: str,
) -> None:
    if await index_exists(conn, index_name, table, dialect):
        log.info("  ✅ index %-28s already exists — skipped", index_name)
        return
    # IF NOT EXISTS supported on SQLite 3.3+ and PostgreSQL 9.5+
    if dialect in ("sqlite", "postgresql"):
        sql = f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({columns_expr})"
    else:
        sql = f"CREATE INDEX {index_name} ON {table} ({columns_expr})"
    await conn.execute(text(sql))
    log.info("  ✅ index %-28s CREATED", index_name)


# ─── JSON type helper ─────────────────────────────────────────────────────────
# PostgreSQL has a native JSON type; SQLite stores JSON as TEXT.

def json_type(dialect: str) -> str:
    return "JSONB" if dialect == "postgresql" else "JSON"


# ─── Migration steps ──────────────────────────────────────────────────────────

async def migrate_candidates(conn, dialect: str) -> None:
    log.info("── candidates ─────────────────────────────────────────────")
    J = json_type(dialect)

    # Columns
    await add_column(conn, "candidates", "is_archived",        "BOOLEAN NOT NULL DEFAULT 0", dialect)
    await add_column(conn, "candidates", "file_hash",          "VARCHAR(64)",                dialect)
    await add_column(conn, "candidates", "user_id",            "VARCHAR(36)",                dialect)
    await add_column(conn, "candidates", "work_experience",    J,                            dialect)
    await add_column(conn, "candidates", "skill_years",        J,                            dialect)
    await add_column(conn, "candidates", "career_breaks",      J,                            dialect)
    await add_column(conn, "candidates", "location_match_pct", "FLOAT",                      dialect)
    await add_column(conn, "candidates", "score_breakdown",    J,                            dialect)
    # BUG 2 FIX — parsed location was never persisted; pool re-scoring always
    # got None from getattr(c, "location", None) → loc_pct stuck at 50.
    await add_column(conn, "candidates", "location",           "VARCHAR(255)",               dialect)

    # Indexes
    await add_index(conn, "ix_candidates_file_hash",   "candidates", "file_hash",         dialect)
    await add_index(conn, "ix_candidates_job_id",      "candidates", "job_id",             dialect)
    # BUG 7 FIX — GET /resumes/all-data orders by created_at DESC with no index;
    # full table scan + sort at scale (10k+ rows ≈ 2–5 s on PostgreSQL).
    await add_index(conn, "ix_candidates_created_at",  "candidates", "created_at DESC",    dialect)


async def migrate_job_descriptions(conn, dialect: str) -> None:
    log.info("── job_descriptions ────────────────────────────────────────")
    await add_column(conn, "job_descriptions", "salary_range",          "VARCHAR(100)", dialect)
    await add_column(conn, "job_descriptions", "file_hash",             "VARCHAR(64)",  dialect)
    await add_column(conn, "job_descriptions", "education_requirement", "VARCHAR(20)",  dialect)


async def migrate_stored_resumes(conn, dialect: str) -> None:
    log.info("── stored_resumes ──────────────────────────────────────────")
    J = json_type(dialect)
    F = "FLOAT" if dialect == "postgresql" else "REAL"

    cols = [
        ("file_hash",         "VARCHAR(64)"),
        ("parsed_name",       "VARCHAR(255)"),
        ("parsed_email",      "VARCHAR(255)"),
        ("parsed_phone",      "VARCHAR(50)"),
        ("parsed_location",   "VARCHAR(255)"),
        ("skills",            J),
        ("normalized_skills", J),
        ("experience_years",  F),
        ("education",         J),
        ("projects",          J),
        ("work_experience",   J),
        ("skill_years",       J),
        ("career_breaks",     J),
        ("embedding",         J),
        ("summary",           "TEXT"),
        ("parse_version",     "INTEGER DEFAULT 1"),
    ]
    for col, col_type in cols:
        await add_column(conn, "stored_resumes", col, col_type, dialect)


# ─── Entry point ──────────────────────────────────────────────────────────────

async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    dialect = engine.dialect.name
    log.info("Jobora unified migration starting — dialect: %s", dialect)
    log.info("DATABASE_URL: %s", settings.DATABASE_URL.split("@")[-1])  # hide creds

    async with engine.begin() as conn:
        await migrate_candidates(conn, dialect)
        await migrate_job_descriptions(conn, dialect)
        await migrate_stored_resumes(conn, dialect)

    await engine.dispose()

    log.info("")
    log.info("═══════════════════════════════════════════════════════════")
    log.info("  Migration complete — all columns and indexes are in place.")
    log.info("  Restart the backend server to pick up the changes.")
    log.info("═══════════════════════════════════════════════════════════")


if __name__ == "__main__":
    asyncio.run(main())
