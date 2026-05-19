"""create used_reset_tokens table for one-time reset token enforcement

Revision ID: f5e6f7a8b9c0
Revises: f4d5e6f7a8b9
Create Date: 2026-05-15 08:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f5e6f7a8b9c0"
down_revision: Union[str, None] = "f4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "used_reset_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_used_reset_tokens_user_id", "used_reset_tokens", ["user_id"], unique=False)
    op.create_index("ix_used_reset_tokens_jti", "used_reset_tokens", ["jti"], unique=True)
    op.create_index("ix_used_reset_tokens_used_at", "used_reset_tokens", ["used_at"], unique=False)
    op.create_index("ix_used_reset_tokens_expires_at", "used_reset_tokens", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_used_reset_tokens_expires_at", table_name="used_reset_tokens")
    op.drop_index("ix_used_reset_tokens_used_at", table_name="used_reset_tokens")
    op.drop_index("ix_used_reset_tokens_jti", table_name="used_reset_tokens")
    op.drop_index("ix_used_reset_tokens_user_id", table_name="used_reset_tokens")
    op.drop_table("used_reset_tokens")
