"""add per-user pool unique index on lower(email)

Revision ID: f6a7b8c9d0e1
Revises: f5e6f7a8b9c0
Create Date: 2026-05-15 10:40:00.000000
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "f5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Backfill safety: dedupe existing pool candidates that would violate the
    # new per-user case-insensitive email uniqueness rule.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY lower(email), user_id
                    ORDER BY updated_at DESC, created_at DESC, id DESC
                ) AS rn
            FROM candidates
            WHERE job_id IS NULL
              AND email IS NOT NULL
              AND user_id IS NOT NULL
        )
        DELETE FROM candidates
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pool_candidate_email_user
        ON candidates (lower(email), user_id)
        WHERE job_id IS NULL AND email IS NOT NULL AND user_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_pool_candidate_email_user")
