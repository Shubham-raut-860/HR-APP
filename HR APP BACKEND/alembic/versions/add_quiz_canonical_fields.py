"""Add canonical quiz fields to candidates.

Revision ID: a9c8e7d6f5b4
Revises: e1a2b3c4d5e6
Create Date: 2026-05-12 03:15:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a9c8e7d6f5b4"
down_revision: Union[str, None] = "e1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(c.get("name") == column for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, "candidates"):
        if _has_column(inspector, "candidates", "quiz_max") is False:
            op.add_column("candidates", sa.Column("quiz_max", sa.Float(), nullable=True))
        if _has_column(inspector, "candidates", "quiz_pct") is False:
            op.add_column("candidates", sa.Column("quiz_pct", sa.Float(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, "candidates"):
        if _has_column(inspector, "candidates", "quiz_pct"):
            op.drop_column("candidates", "quiz_pct")
        if _has_column(inspector, "candidates", "quiz_max"):
            op.drop_column("candidates", "quiz_max")

