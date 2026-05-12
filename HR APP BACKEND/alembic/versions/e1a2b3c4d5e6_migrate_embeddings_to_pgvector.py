"""migrate embeddings to pgvector

Revision ID: e1a2b3c4d5e6
Revises: d4f1b2c3e4f5
Create Date: 2026-05-09 01:25:00.000000
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "e1a2b3c4d5e6"
down_revision: Union[str, None] = "d4f1b2c3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    op.execute(
        """
        ALTER TABLE job_descriptions
        ALTER COLUMN embedding TYPE vector(1536)
        USING (
            CASE
                WHEN embedding IS NULL THEN NULL
                ELSE embedding::text::vector
            END
        );
        """
    )
    op.execute(
        """
        ALTER TABLE candidates
        ALTER COLUMN embedding TYPE vector(1536)
        USING (
            CASE
                WHEN embedding IS NULL THEN NULL
                ELSE embedding::text::vector
            END
        );
        """
    )
    op.execute(
        """
        ALTER TABLE stored_resumes
        ALTER COLUMN embedding TYPE vector(1536)
        USING (
            CASE
                WHEN embedding IS NULL THEN NULL
                ELSE embedding::text::vector
            END
        );
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_descriptions_embedding_hnsw "
        "ON job_descriptions USING hnsw (embedding vector_cosine_ops);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidates_embedding_hnsw "
        "ON candidates USING hnsw (embedding vector_cosine_ops);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_stored_resumes_embedding_hnsw "
        "ON stored_resumes USING hnsw (embedding vector_cosine_ops);"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_stored_resumes_embedding_hnsw;")
    op.execute("DROP INDEX IF EXISTS ix_candidates_embedding_hnsw;")
    op.execute("DROP INDEX IF EXISTS ix_job_descriptions_embedding_hnsw;")

    op.execute(
        """
        ALTER TABLE stored_resumes
        ALTER COLUMN embedding TYPE json
        USING (
            CASE
                WHEN embedding IS NULL THEN NULL
                ELSE embedding::text::json
            END
        );
        """
    )
    op.execute(
        """
        ALTER TABLE candidates
        ALTER COLUMN embedding TYPE json
        USING (
            CASE
                WHEN embedding IS NULL THEN NULL
                ELSE embedding::text::json
            END
        );
        """
    )
    op.execute(
        """
        ALTER TABLE job_descriptions
        ALTER COLUMN embedding TYPE json
        USING (
            CASE
                WHEN embedding IS NULL THEN NULL
                ELSE embedding::text::json
            END
        );
        """
    )

