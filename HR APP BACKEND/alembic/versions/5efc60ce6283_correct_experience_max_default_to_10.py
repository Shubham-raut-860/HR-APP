"""Correct experience_max default to 10

Revision ID: 5efc60ce6283
Revises: 
Create Date: 2026-04-02 02:01:13.043724
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5efc60ce6283'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def _has_table(table: str) -> bool:
        return table in inspector.get_table_names()

    def _has_index(table: str, index_name: str) -> bool:
        if not _has_table(table):
            return False
        return any(i.get("name") == index_name for i in inspector.get_indexes(table))

    def _has_column(table: str, column_name: str) -> bool:
        if not _has_table(table):
            return False
        return any(c.get("name") == column_name for c in inspector.get_columns(table))

    if _has_table("audit_logs") and not _has_index("audit_logs", op.f("ix_audit_logs_created_at")):
        op.create_index(op.f("ix_audit_logs_created_at"), "audit_logs", ["created_at"], unique=False)
    if _has_table("audit_logs") and not _has_index("audit_logs", op.f("ix_audit_logs_user_id")):
        op.create_index(op.f("ix_audit_logs_user_id"), "audit_logs", ["user_id"], unique=False)
    if _has_table("candidates") and not _has_index("candidates", op.f("ix_candidates_user_id")):
        op.create_index(op.f("ix_candidates_user_id"), "candidates", ["user_id"], unique=False)
    if _has_table("job_descriptions") and not _has_index("job_descriptions", op.f("ix_job_descriptions_file_hash")):
        op.create_index(op.f("ix_job_descriptions_file_hash"), "job_descriptions", ["file_hash"], unique=False)
    if _has_table("questions") and not _has_index("questions", op.f("ix_questions_quiz_id")):
        op.create_index(op.f("ix_questions_quiz_id"), "questions", ["quiz_id"], unique=False)
    if _has_table("quiz_attempts") and not _has_column("quiz_attempts", "token_expires_at"):
        op.add_column("quiz_attempts", sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True))
    if _has_table("quiz_attempts") and not _has_index("quiz_attempts", op.f("ix_quiz_attempts_candidate_id")):
        op.create_index(op.f("ix_quiz_attempts_candidate_id"), "quiz_attempts", ["candidate_id"], unique=False)
    if _has_table("quizzes") and not _has_index("quizzes", op.f("ix_quizzes_job_id")):
        op.create_index(op.f("ix_quizzes_job_id"), "quizzes", ["job_id"], unique=False)
    if _has_table("stored_resumes") and not _has_index("stored_resumes", op.f("ix_stored_resumes_file_hash")):
        op.create_index(op.f("ix_stored_resumes_file_hash"), "stored_resumes", ["file_hash"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def _has_table(table: str) -> bool:
        return table in inspector.get_table_names()

    def _has_index(table: str, index_name: str) -> bool:
        if not _has_table(table):
            return False
        return any(i.get("name") == index_name for i in inspector.get_indexes(table))

    def _has_column(table: str, column_name: str) -> bool:
        if not _has_table(table):
            return False
        return any(c.get("name") == column_name for c in inspector.get_columns(table))

    if _has_table("stored_resumes") and _has_index("stored_resumes", op.f("ix_stored_resumes_file_hash")):
        op.drop_index(op.f("ix_stored_resumes_file_hash"), table_name="stored_resumes")
    if _has_table("quizzes") and _has_index("quizzes", op.f("ix_quizzes_job_id")):
        op.drop_index(op.f("ix_quizzes_job_id"), table_name="quizzes")
    if _has_table("quiz_attempts") and _has_index("quiz_attempts", op.f("ix_quiz_attempts_candidate_id")):
        op.drop_index(op.f("ix_quiz_attempts_candidate_id"), table_name="quiz_attempts")
    if _has_table("quiz_attempts") and _has_column("quiz_attempts", "token_expires_at"):
        op.drop_column("quiz_attempts", "token_expires_at")
    if _has_table("questions") and _has_index("questions", op.f("ix_questions_quiz_id")):
        op.drop_index(op.f("ix_questions_quiz_id"), table_name="questions")
    if _has_table("job_descriptions") and _has_index("job_descriptions", op.f("ix_job_descriptions_file_hash")):
        op.drop_index(op.f("ix_job_descriptions_file_hash"), table_name="job_descriptions")
    if _has_table("candidates") and _has_index("candidates", op.f("ix_candidates_user_id")):
        op.drop_index(op.f("ix_candidates_user_id"), table_name="candidates")
    if _has_table("audit_logs") and _has_index("audit_logs", op.f("ix_audit_logs_user_id")):
        op.drop_index(op.f("ix_audit_logs_user_id"), table_name="audit_logs")
    if _has_table("audit_logs") and _has_index("audit_logs", op.f("ix_audit_logs_created_at")):
        op.drop_index(op.f("ix_audit_logs_created_at"), table_name="audit_logs")
