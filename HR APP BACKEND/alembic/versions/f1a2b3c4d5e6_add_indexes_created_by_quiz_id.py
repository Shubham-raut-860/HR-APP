"""Add missing indexes for job_descriptions.created_by and quiz_attempts.quiz_id.

Revision ID: f1a2b3c4d5e6
Revises: a9c8e7d6f5b4
Create Date: 2026-05-15 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "a9c8e7d6f5b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_index(inspector: sa.Inspector, table: str, index_name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(i.get("name") == index_name for i in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "job_descriptions") and not _has_index(
        inspector, "job_descriptions", "ix_job_descriptions_created_by"
    ):
        op.create_index(
            "ix_job_descriptions_created_by",
            "job_descriptions",
            ["created_by"],
            unique=False,
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, "quiz_attempts") and not _has_index(
        inspector, "quiz_attempts", "ix_quiz_attempts_quiz_id"
    ):
        op.create_index(
            "ix_quiz_attempts_quiz_id",
            "quiz_attempts",
            ["quiz_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "quiz_attempts") and _has_index(
        inspector, "quiz_attempts", "ix_quiz_attempts_quiz_id"
    ):
        op.drop_index("ix_quiz_attempts_quiz_id", table_name="quiz_attempts")

    inspector = sa.inspect(bind)
    if _has_table(inspector, "job_descriptions") and _has_index(
        inspector, "job_descriptions", "ix_job_descriptions_created_by"
    ):
        op.drop_index("ix_job_descriptions_created_by", table_name="job_descriptions")

