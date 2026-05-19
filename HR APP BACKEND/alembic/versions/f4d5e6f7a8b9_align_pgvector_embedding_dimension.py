"""Align pgvector embedding column dimensions with configured EMBEDDING_DIM.

Revision ID: f4d5e6f7a8b9
Revises: f3c4d5e6f7a8
Create Date: 2026-05-15 00:40:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import os


# revision identifiers, used by Alembic.
revision: str = "f4d5e6f7a8b9"
down_revision: Union[str, None] = "f3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_VECTOR_TABLE_COLUMNS = (
    ("job_descriptions", "embedding"),
    ("candidates", "embedding"),
    ("stored_resumes", "embedding"),
)
_INDEXES = (
    "ix_job_descriptions_embedding_hnsw",
    "ix_candidates_embedding_hnsw",
    "ix_stored_resumes_embedding_hnsw",
)
_SUPPORTED_DIMS = (1536, 3072)


def _has_table(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(c.get("name") == column for c in inspector.get_columns(table))


def _validate_dim() -> int:
    raw_dim = (os.getenv("EMBEDDING_DIM") or "").strip()
    if raw_dim:
        dim = int(raw_dim)
    else:
        deployment = (os.getenv("AZURE_EMBEDDING_DEPLOYMENT") or "").strip().lower()
        known_dims = {
            "text-embedding-ada-002": 1536,
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
        }
        dim = 1536
        for model_name, model_dim in known_dims.items():
            if deployment == model_name or model_name in deployment:
                dim = model_dim
                break
    if dim not in _SUPPORTED_DIMS:
        raise RuntimeError(
            f"Unsupported EMBEDDING_DIM={dim}. Expected one of {_SUPPORTED_DIMS}."
        )
    return dim


def _apply_vector_dimension(dim: int) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for idx_name in _INDEXES:
        op.execute(sa.text(f"DROP INDEX IF EXISTS {idx_name};"))

    for table_name, column_name in _VECTOR_TABLE_COLUMNS:
        if not _has_column(inspector, table_name, column_name):
            continue
        op.execute(
            sa.text(
                f"""
                ALTER TABLE {table_name}
                ALTER COLUMN {column_name} TYPE vector({dim})
                USING (
                    CASE
                        WHEN {column_name} IS NULL THEN NULL
                        ELSE {column_name}::text::vector
                    END
                );
                """
            )
        )

    if _has_column(inspector, "job_descriptions", "embedding"):
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_job_descriptions_embedding_hnsw "
                "ON job_descriptions USING hnsw (embedding vector_cosine_ops);"
            )
        )
    if _has_column(inspector, "candidates", "embedding"):
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_candidates_embedding_hnsw "
                "ON candidates USING hnsw (embedding vector_cosine_ops);"
            )
        )
    if _has_column(inspector, "stored_resumes", "embedding"):
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_stored_resumes_embedding_hnsw "
                "ON stored_resumes USING hnsw (embedding vector_cosine_ops);"
            )
        )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    dim = _validate_dim()
    _apply_vector_dimension(dim)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    _apply_vector_dimension(1536)
