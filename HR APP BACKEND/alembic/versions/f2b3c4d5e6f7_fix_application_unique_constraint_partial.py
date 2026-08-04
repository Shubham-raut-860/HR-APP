"""Fix candidate application uniqueness with partial index and ownership check.

Revision ID: f2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-05-15 00:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f2b3c4d5e6f7"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "candidates"
_UNIQUE_NAME = "uq_application_user_job"
_CHECK_NAME = "ck_candidates_job_or_user_present"
_PARTIAL_WHERE = "user_id IS NOT NULL AND job_id IS NOT NULL"


def _has_table(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_unique_constraint(inspector: sa.Inspector, table: str, constraint_name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(c.get("name") == constraint_name for c in inspector.get_unique_constraints(table))


def _has_index(inspector: sa.Inspector, table: str, index_name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(i.get("name") == index_name for i in inspector.get_indexes(table))


def _has_check_constraint(inspector: sa.Inspector, table: str, constraint_name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    try:
        checks = inspector.get_check_constraints(table)
    except NotImplementedError:
        return False
    return any(c.get("name") == constraint_name for c in checks)


def _ensure_no_conflicting_rows(bind: sa.engine.Connection) -> None:
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
            "Cannot create partial unique index uq_application_user_job: "
            "duplicate (user_id, job_id) rows already exist."
        )

    orphan_count = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM candidates
            WHERE user_id IS NULL AND job_id IS NULL
            """
        )
    ).scalar_one()
    if int(orphan_count or 0) > 0:
        raise RuntimeError(
            "Cannot add ck_candidates_job_or_user_present: "
            "rows exist where both user_id and job_id are NULL."
        )


def _drop_legacy_application_uniqueness(bind: sa.engine.Connection) -> None:
    if bind.dialect.name == "sqlite":
        # SQLite UNIQUE constraints already permit multiple NULL values and
        # require batch table rebuilds to drop constraints. Keep legacy shape.
        return

    inspector = sa.inspect(bind)
    if _has_unique_constraint(inspector, _TABLE, _UNIQUE_NAME):
        op.drop_constraint(_UNIQUE_NAME, _TABLE, type_="unique")

    inspector = sa.inspect(bind)
    if _has_index(inspector, _TABLE, _UNIQUE_NAME):
        op.drop_index(_UNIQUE_NAME, table_name=_TABLE)


def _create_partial_unique_index(bind: sa.engine.Connection) -> None:
    inspector = sa.inspect(bind)
    if _has_index(inspector, _TABLE, _UNIQUE_NAME) or _has_unique_constraint(
        inspector, _TABLE, _UNIQUE_NAME
    ):
        return

    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute(
            sa.text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {_UNIQUE_NAME} "
                f"ON {_TABLE} (user_id, job_id) WHERE {_PARTIAL_WHERE}"
            )
        )
    elif dialect == "sqlite":
        op.create_index(
            _UNIQUE_NAME,
            _TABLE,
            ["user_id", "job_id"],
            unique=True,
            sqlite_where=sa.text(_PARTIAL_WHERE),
        )
    else:
        op.create_index(_UNIQUE_NAME, _TABLE, ["user_id", "job_id"], unique=True)


def _create_presence_check_constraint(bind: sa.engine.Connection) -> None:
    inspector = sa.inspect(bind)
    if _has_check_constraint(inspector, _TABLE, _CHECK_NAME):
        return

    constraint_sql = "job_id IS NOT NULL OR user_id IS NOT NULL"
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.create_check_constraint(_CHECK_NAME, constraint_sql)
    else:
        op.create_check_constraint(_CHECK_NAME, _TABLE, constraint_sql)


def _drop_presence_check_constraint(bind: sa.engine.Connection) -> None:
    inspector = sa.inspect(bind)
    if not _has_check_constraint(inspector, _TABLE, _CHECK_NAME):
        return

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.drop_constraint(_CHECK_NAME, type_="check")
    else:
        op.drop_constraint(_CHECK_NAME, _TABLE, type_="check")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return

    _ensure_no_conflicting_rows(bind)
    _drop_legacy_application_uniqueness(bind)
    _create_partial_unique_index(bind)
    _create_presence_check_constraint(bind)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return

    _drop_presence_check_constraint(bind)

    inspector = sa.inspect(bind)
    if _has_index(inspector, _TABLE, _UNIQUE_NAME):
        op.drop_index(_UNIQUE_NAME, table_name=_TABLE)

    inspector = sa.inspect(bind)
    if not _has_unique_constraint(inspector, _TABLE, _UNIQUE_NAME):
        if bind.dialect.name == "sqlite":
            op.create_index(_UNIQUE_NAME, _TABLE, ["user_id", "job_id"], unique=True)
        else:
            op.create_unique_constraint(_UNIQUE_NAME, _TABLE, ["user_id", "job_id"])
