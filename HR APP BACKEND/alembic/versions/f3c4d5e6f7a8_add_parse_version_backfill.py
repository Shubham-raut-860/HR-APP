"""Backfill stored resume parse_version to force reparse.

Revision ID: f3c4d5e6f7a8
Revises: f2b3c4d5e6f7
Create Date: 2026-05-15 00:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f3c4d5e6f7a8"
down_revision: Union[str, None] = "f2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "stored_resumes"
_COLUMN = "parse_version"


def _has_table(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(c.get("name") == column for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, _TABLE, _COLUMN):
        return

    bind.execute(sa.text(f"UPDATE {_TABLE} SET {_COLUMN} = 0"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, _TABLE, _COLUMN):
        return

    bind.execute(sa.text(f"UPDATE {_TABLE} SET {_COLUMN} = 1 WHERE {_COLUMN} = 0"))
