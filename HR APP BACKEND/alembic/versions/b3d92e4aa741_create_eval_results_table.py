"""Create eval_results table for unified evaluation history.

Revision ID: b3d92e4aa741
Revises: 6e117dff635b
Create Date: 2026-05-08 23:40:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3d92e4aa741"
down_revision: Union[str, None] = "6e117dff635b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_index(inspector: sa.Inspector, table: str, name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(idx.get("name") == name for idx in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "eval_results"):
        op.create_table(
            "eval_results",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("operation", sa.String(length=50), nullable=False),
            sa.Column("overall_score", sa.Float(), nullable=False),
            sa.Column("passed", sa.Boolean(), nullable=False),
            sa.Column("deepeval_json", sa.Text(), nullable=True),
            sa.Column("ragas_json", sa.Text(), nullable=True),
            sa.Column("latency_ms", sa.Float(), nullable=True),
            sa.Column(
                "evaluated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name="fk_eval_user",
                ondelete="CASCADE",
            ),
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, "eval_results") and not _has_index(inspector, "eval_results", "idx_eval_results_user_id"):
        op.create_index("idx_eval_results_user_id", "eval_results", ["user_id"], unique=False)
    if _has_table(inspector, "eval_results") and not _has_index(inspector, "eval_results", "idx_eval_results_operation"):
        op.create_index("idx_eval_results_operation", "eval_results", ["operation"], unique=False)
    if _has_table(inspector, "eval_results") and not _has_index(inspector, "eval_results", "idx_eval_results_evaluated"):
        op.create_index("idx_eval_results_evaluated", "eval_results", ["evaluated_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "eval_results"):
        if _has_index(inspector, "eval_results", "idx_eval_results_evaluated"):
            op.drop_index("idx_eval_results_evaluated", table_name="eval_results")
        if _has_index(inspector, "eval_results", "idx_eval_results_operation"):
            op.drop_index("idx_eval_results_operation", table_name="eval_results")
        if _has_index(inspector, "eval_results", "idx_eval_results_user_id"):
            op.drop_index("idx_eval_results_user_id", table_name="eval_results")
        op.drop_table("eval_results")
