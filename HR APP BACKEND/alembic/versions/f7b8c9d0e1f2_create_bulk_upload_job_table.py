"""create bulk_upload_jobs table for async status persistence

Revision ID: f7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-15 10:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bulk_upload_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("processed", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("last_committed_batch", sa.Integer(), nullable=False),
        sa.Column("error_summary", sa.JSON(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["job_descriptions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bulk_upload_jobs_status", "bulk_upload_jobs", ["status"], unique=False)
    op.create_index("ix_bulk_upload_jobs_created_by", "bulk_upload_jobs", ["created_by"], unique=False)
    op.create_index("ix_bulk_upload_jobs_job_id", "bulk_upload_jobs", ["job_id"], unique=False)
    op.create_index("ix_bulk_upload_jobs_created_at", "bulk_upload_jobs", ["created_at"], unique=False)
    op.create_index("ix_bulk_upload_jobs_updated_at", "bulk_upload_jobs", ["updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_bulk_upload_jobs_updated_at", table_name="bulk_upload_jobs")
    op.drop_index("ix_bulk_upload_jobs_created_at", table_name="bulk_upload_jobs")
    op.drop_index("ix_bulk_upload_jobs_job_id", table_name="bulk_upload_jobs")
    op.drop_index("ix_bulk_upload_jobs_created_by", table_name="bulk_upload_jobs")
    op.drop_index("ix_bulk_upload_jobs_status", table_name="bulk_upload_jobs")
    op.drop_table("bulk_upload_jobs")
