"""Add unique application guard on (user_id, job_id).

Revision ID: 9f2a1c7b4d11
Revises: 8d3b9c6f1a22
Create Date: 2026-05-08 22:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9f2a1c7b4d11"
down_revision: Union[str, None] = "8d3b9c6f1a22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_unique_constraint(inspector: sa.Inspector, table: str, constraint_name: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return any(c.get("name") == constraint_name for c in inspector.get_unique_constraints(table))


def _has_index(inspector: sa.Inspector, table: str, index_name: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return any(i.get("name") == index_name for i in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    name = "uq_application_user_job"

    if "candidates" not in inspector.get_table_names():
        return

    if _has_unique_constraint(inspector, "candidates", name) or _has_index(inspector, "candidates", name):
        return

    duplicate_pairs = bind.execute(
        sa.text(
            """
            SELECT user_id, job_id, COUNT(*) AS c
            FROM candidates
            WHERE user_id IS NOT NULL AND job_id IS NOT NULL
            GROUP BY user_id, job_id
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()
    if duplicate_pairs:
        raise RuntimeError(
            "Cannot add uq_application_user_job: existing duplicate (user_id, job_id) rows found in candidates."
        )

    # SQLite cannot add a named UNIQUE constraint post-create without table rebuild.
    # Use a unique index with the requested name as equivalent conflict target.
    if bind.dialect.name == "sqlite":
        op.create_index(name, "candidates", ["user_id", "job_id"], unique=True)
    else:
        op.create_unique_constraint(name, "candidates", ["user_id", "job_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    name = "uq_application_user_job"

    if bind.dialect.name == "sqlite":
        if _has_index(inspector, "candidates", name):
            op.drop_index(name, table_name="candidates")
    else:
        if _has_unique_constraint(inspector, "candidates", name):
            op.drop_constraint(name, "candidates", type_="unique")
