"""Add refresh/revoked token tables and user token revocation watermark.

Revision ID: d4f1b2c3e4f5
Revises: c7a7d9f8b2e1
Create Date: 2026-05-09 03:35:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4f1b2c3e4f5"
down_revision: Union[str, None] = "c7a7d9f8b2e1"
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

    if not _has_column(inspector, "users", "token_revoked_before"):
        op.add_column("users", sa.Column("token_revoked_before", sa.DateTime(timezone=True), nullable=True))

    if not _has_table(inspector, "refresh_tokens"):
        op.create_table(
            "refresh_tokens",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("replaced_by_token_hash", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash"),
        )
        op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"], unique=False)
        op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)
        op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"], unique=False)
        op.create_index("ix_refresh_tokens_revoked_at", "refresh_tokens", ["revoked_at"], unique=False)
        op.create_index("ix_refresh_tokens_created_at", "refresh_tokens", ["created_at"], unique=False)

    if not _has_table(inspector, "revoked_tokens"):
        op.create_table(
            "revoked_tokens",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=True),
            sa.Column("jti", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("jti"),
        )
        op.create_index("ix_revoked_tokens_user_id", "revoked_tokens", ["user_id"], unique=False)
        op.create_index("ix_revoked_tokens_jti", "revoked_tokens", ["jti"], unique=True)
        op.create_index("ix_revoked_tokens_expires_at", "revoked_tokens", ["expires_at"], unique=False)
        op.create_index("ix_revoked_tokens_revoked_at", "revoked_tokens", ["revoked_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "revoked_tokens"):
        op.drop_index("ix_revoked_tokens_revoked_at", table_name="revoked_tokens")
        op.drop_index("ix_revoked_tokens_expires_at", table_name="revoked_tokens")
        op.drop_index("ix_revoked_tokens_jti", table_name="revoked_tokens")
        op.drop_index("ix_revoked_tokens_user_id", table_name="revoked_tokens")
        op.drop_table("revoked_tokens")

    if _has_table(inspector, "refresh_tokens"):
        op.drop_index("ix_refresh_tokens_created_at", table_name="refresh_tokens")
        op.drop_index("ix_refresh_tokens_revoked_at", table_name="refresh_tokens")
        op.drop_index("ix_refresh_tokens_expires_at", table_name="refresh_tokens")
        op.drop_index("ix_refresh_tokens_token_hash", table_name="refresh_tokens")
        op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
        op.drop_table("refresh_tokens")

    if _has_column(inspector, "users", "token_revoked_before"):
        op.drop_column("users", "token_revoked_before")
