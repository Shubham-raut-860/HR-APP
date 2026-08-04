"""Add missing scoring and resume columns used by runtime models.

Revision ID: 8d3b9c6f1a22
Revises: 5efc60ce6283
Create Date: 2026-05-08 16:20:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8d3b9c6f1a22"
down_revision: Union[str, None] = "5efc60ce6283"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(c.get("name") == column for c in inspector.get_columns(table))


def _has_index(inspector: sa.Inspector, table: str, index_name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(i.get("name") == index_name for i in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # job_descriptions
    if _has_table(inspector, "job_descriptions"):
        if _has_column(inspector, "job_descriptions", "education_requirement") is False:
            op.add_column("job_descriptions", sa.Column("education_requirement", sa.String(length=20), nullable=True))
        if _has_column(inspector, "job_descriptions", "file_hash") is False:
            op.add_column("job_descriptions", sa.Column("file_hash", sa.String(length=64), nullable=True))
        if _has_column(inspector, "job_descriptions", "salary_range") is False:
            op.add_column("job_descriptions", sa.Column("salary_range", sa.String(length=100), nullable=True))
        if _has_index(inspector, "job_descriptions", "ix_job_descriptions_file_hash") is False and _has_column(inspector, "job_descriptions", "file_hash"):
            op.create_index("ix_job_descriptions_file_hash", "job_descriptions", ["file_hash"], unique=False)

    # candidates
    if _has_table(inspector, "candidates"):
        if _has_column(inspector, "candidates", "location") is False:
            op.add_column("candidates", sa.Column("location", sa.String(length=255), nullable=True))
        if _has_column(inspector, "candidates", "file_hash") is False:
            op.add_column("candidates", sa.Column("file_hash", sa.String(length=64), nullable=True))
        if _has_column(inspector, "candidates", "is_archived") is False:
            op.add_column(
                "candidates",
                sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            )
        if _has_column(inspector, "candidates", "location_match_pct") is False:
            op.add_column("candidates", sa.Column("location_match_pct", sa.Float(), nullable=True))
        if _has_column(inspector, "candidates", "score_breakdown") is False:
            op.add_column("candidates", sa.Column("score_breakdown", sa.JSON(), nullable=True))
        if _has_column(inspector, "candidates", "career_breaks") is False:
            op.add_column("candidates", sa.Column("career_breaks", sa.JSON(), nullable=True))
        if _has_index(inspector, "candidates", "ix_candidates_file_hash") is False and _has_column(inspector, "candidates", "file_hash"):
            op.create_index("ix_candidates_file_hash", "candidates", ["file_hash"], unique=False)

    # stored_resumes
    if _has_table(inspector, "stored_resumes"):
        if _has_column(inspector, "stored_resumes", "file_hash") is False:
            op.add_column("stored_resumes", sa.Column("file_hash", sa.String(length=64), nullable=True))
        if _has_column(inspector, "stored_resumes", "career_breaks") is False:
            op.add_column("stored_resumes", sa.Column("career_breaks", sa.JSON(), nullable=True))
        if _has_index(inspector, "stored_resumes", "ix_stored_resumes_file_hash") is False and _has_column(inspector, "stored_resumes", "file_hash"):
            op.create_index("ix_stored_resumes_file_hash", "stored_resumes", ["file_hash"], unique=False)


def downgrade() -> None:
    # Intentionally no-op: this migration backfills missing columns in mixed environments.
    pass
