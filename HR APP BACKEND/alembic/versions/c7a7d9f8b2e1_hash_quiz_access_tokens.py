"""Rename quiz token column to token_hash and backfill SHA-256 hashes.

Revision ID: c7a7d9f8b2e1
Revises: b3d92e4aa741
Create Date: 2026-05-09 00:20:00.000000
"""

from typing import Sequence, Union
import hashlib

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c7a7d9f8b2e1"
down_revision: Union[str, None] = "b3d92e4aa741"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(c.get("name") == column for c in inspector.get_columns(table))


def _has_index(inspector: sa.Inspector, table: str, index_name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(i.get("name") == index_name for i in inspector.get_indexes(table))


def _is_sha256_hex(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _rename_access_token_to_token_hash(bind: sa.engine.Connection, inspector: sa.Inspector) -> None:
    if _has_column(inspector, "quiz_attempts", "token_hash"):
        return
    if not _has_column(inspector, "quiz_attempts", "access_token"):
        op.add_column("quiz_attempts", sa.Column("token_hash", sa.String(length=64), nullable=True))
        return

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("quiz_attempts") as batch_op:
            batch_op.alter_column(
                "access_token",
                new_column_name="token_hash",
                existing_type=sa.String(length=255),
                existing_nullable=False,
            )
    else:
        op.alter_column(
            "quiz_attempts",
            "access_token",
            new_column_name="token_hash",
            existing_type=sa.String(length=255),
            existing_nullable=False,
        )


def _rename_token_hash_to_access_token(bind: sa.engine.Connection, inspector: sa.Inspector) -> None:
    if _has_column(inspector, "quiz_attempts", "access_token"):
        return
    if not _has_column(inspector, "quiz_attempts", "token_hash"):
        return

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("quiz_attempts") as batch_op:
            batch_op.alter_column(
                "token_hash",
                new_column_name="access_token",
                existing_type=sa.String(length=64),
                existing_nullable=False,
            )
    else:
        op.alter_column(
            "quiz_attempts",
            "token_hash",
            new_column_name="access_token",
            existing_type=sa.String(length=64),
            existing_nullable=False,
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, "quiz_attempts"):
        return

    _rename_access_token_to_token_hash(bind, inspector)

    # Backfill existing raw token values to SHA-256 hashes.
    rows = bind.execute(
        sa.text(
            "SELECT id, token_hash FROM quiz_attempts WHERE token_hash IS NOT NULL"
        )
    ).mappings().all()
    for row in rows:
        token_value = row["token_hash"]
        if isinstance(token_value, str) and not _is_sha256_hex(token_value):
            bind.execute(
                sa.text(
                    "UPDATE quiz_attempts SET token_hash = :hashed WHERE id = :attempt_id"
                ),
                {
                    "hashed": hashlib.sha256(token_value.encode("utf-8")).hexdigest(),
                    "attempt_id": row["id"],
                },
            )

    null_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM quiz_attempts WHERE token_hash IS NULL")
    ).scalar_one()

    if null_count == 0:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("quiz_attempts") as batch_op:
                batch_op.alter_column(
                    "token_hash",
                    existing_type=sa.String(length=255),
                    type_=sa.String(length=64),
                    existing_nullable=False,
                    nullable=False,
                )
        else:
            op.alter_column(
                "quiz_attempts",
                "token_hash",
                existing_type=sa.String(length=255),
                type_=sa.String(length=64),
                existing_nullable=False,
                nullable=False,
            )

    inspector = sa.inspect(bind)
    if _has_index(inspector, "quiz_attempts", "ix_quiz_attempts_access_token"):
        op.drop_index("ix_quiz_attempts_access_token", table_name="quiz_attempts")
    inspector = sa.inspect(bind)
    if not _has_index(inspector, "quiz_attempts", "ix_quiz_attempts_token_hash"):
        op.create_index("ix_quiz_attempts_token_hash", "quiz_attempts", ["token_hash"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, "quiz_attempts"):
        return

    if _has_index(inspector, "quiz_attempts", "ix_quiz_attempts_token_hash"):
        op.drop_index("ix_quiz_attempts_token_hash", table_name="quiz_attempts")

    inspector = sa.inspect(bind)
    _rename_token_hash_to_access_token(bind, inspector)

    inspector = sa.inspect(bind)
    if not _has_index(inspector, "quiz_attempts", "ix_quiz_attempts_access_token"):
        op.create_index("ix_quiz_attempts_access_token", "quiz_attempts", ["access_token"], unique=True)
