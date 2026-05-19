"""add quiz attempt snapshot and evaluation counters

Revision ID: f8c9d0e1f2a3
Revises: f7b8c9d0e1f2
Create Date: 2026-05-15 15:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f8c9d0e1f2a3"
down_revision: Union[str, None] = "f7b8c9d0e1f2"
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
    dialect = bind.dialect.name.lower()

    if not _has_table(inspector, "quiz_attempts"):
        return

    added_code_eval_count = False
    added_tab_switches = False

    if not _has_column(inspector, "quiz_attempts", "question_snapshot"):
        op.add_column("quiz_attempts", sa.Column("question_snapshot", sa.JSON(), nullable=True))

    if not _has_column(inspector, "quiz_attempts", "code_eval_count"):
        op.add_column(
            "quiz_attempts",
            sa.Column("code_eval_count", sa.Integer(), nullable=False, server_default="0"),
        )
        added_code_eval_count = True

    if not _has_column(inspector, "quiz_attempts", "tab_switches"):
        op.add_column(
            "quiz_attempts",
            sa.Column("tab_switches", sa.Integer(), nullable=False, server_default="0"),
        )
        added_tab_switches = True

    op.execute(sa.text("UPDATE quiz_attempts SET tab_switches = 0"))
    # SQLite doesn't support ALTER COLUMN DROP DEFAULT; keep defaults there.
    supports_drop_default = dialect != "sqlite"
    if added_code_eval_count and supports_drop_default:
        op.alter_column("quiz_attempts", "code_eval_count", server_default=None)
    if added_tab_switches and supports_drop_default:
        op.alter_column("quiz_attempts", "tab_switches", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "quiz_attempts"):
        return

    if _has_column(inspector, "quiz_attempts", "code_eval_count"):
        op.drop_column("quiz_attempts", "code_eval_count")
    if _has_column(inspector, "quiz_attempts", "tab_switches"):
        op.drop_column("quiz_attempts", "tab_switches")
    if _has_column(inspector, "quiz_attempts", "question_snapshot"):
        op.drop_column("quiz_attempts", "question_snapshot")
