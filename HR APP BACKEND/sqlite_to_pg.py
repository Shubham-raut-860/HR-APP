"""
sqlite_to_pg.py — One-off data migration from SQLite to PostgreSQL
===================================================================
Reads every row from the local SQLite database and inserts it into
the PostgreSQL database whose schema was already created by
create_tables() / migrate_all.py.

Usage (from Backend/):
    .venv\Scripts\python.exe sqlite_to_pg.py
"""

import os
from sqlalchemy import create_engine, MetaData, text

# ─── Configuration ────────────────────────────────────────────────────────────
SQLITE_PATH = os.path.join(os.path.dirname(__file__), "hr_platform.db")
SQLITE_URL = f"sqlite:///{SQLITE_PATH}"
POSTGRES_URL = "postgresql+psycopg2://postgres:hr_password@localhost:5432/hr_platform"

# ─── Table insertion order (parents before children) ──────────────────────────
TABLE_ORDER = [
    "users",
    "audit_logs",
    "job_descriptions",
    "notifications",
    "stored_resumes",
    "candidates",
    "quizzes",
    "questions",
    "quiz_attempts",
    "candidate_notifications",
]


def migrate_data():
    print("=" * 60)
    print("  SQLite → PostgreSQL data migration")
    print("=" * 60)

    sqlite_engine = create_engine(SQLITE_URL)
    pg_engine = create_engine(POSTGRES_URL)

    # Reflect the SOURCE (SQLite) schema so we know what tables/columns exist
    sqlite_meta = MetaData()
    sqlite_meta.reflect(bind=sqlite_engine)

    # Reflect the TARGET (PostgreSQL) schema — create_tables() already ran
    pg_meta = MetaData()
    pg_meta.reflect(bind=pg_engine)

    # Build ordered list: explicit order first, then any extras
    ordered = []
    for name in TABLE_ORDER:
        if name in sqlite_meta.tables and name in pg_meta.tables:
            ordered.append(name)
    for t in sqlite_meta.sorted_tables:
        if t.name not in ordered and t.name in pg_meta.tables:
            ordered.append(t.name)

    total_rows = 0

    with sqlite_engine.connect() as src, pg_engine.begin() as dst:
        for table_name in ordered:
            src_table = sqlite_meta.tables[table_name]
            dst_table = pg_meta.tables[table_name]

            result = src.execute(src_table.select())
            rows = result.fetchall()
            keys = list(result.keys())

            if not rows:
                print(f"  {table_name:30s}  0 rows — skipped")
                continue

            # Only include columns that exist in BOTH source and destination
            dst_col_names = {c.name for c in dst_table.columns}
            common_cols = [k for k in keys if k in dst_col_names]

            data = []
            for row in rows:
                row_dict = dict(zip(keys, row))
                data.append({k: row_dict[k] for k in common_cols})

            try:
                dst.execute(dst_table.insert(), data)
                print(f"  {table_name:30s}  {len(data)} rows — ✅ migrated")
                total_rows += len(data)
            except Exception as e:
                print(f"  {table_name:30s}  ERROR: {e}")

    # Reset PostgreSQL sequences for any auto-increment integer PKs
    with pg_engine.begin() as conn:
        for table_name in ordered:
            dst_table = pg_meta.tables[table_name]
            for col in dst_table.columns:
                if col.primary_key and col.autoincrement and hasattr(col.type, "python_type"):
                    try:
                        if col.type.python_type in (int,):
                            seq_name = f"{table_name}_{col.name}_seq"
                            conn.execute(text(
                                f"SELECT setval('{seq_name}', COALESCE((SELECT MAX({col.name}) FROM {table_name}), 1))"
                            ))
                    except Exception:
                        pass  # table uses UUID PKs — no sequence to reset

    print("-" * 60)
    print(f"  Done! {total_rows} total rows migrated.")
    print("=" * 60)


if __name__ == "__main__":
    migrate_data()
