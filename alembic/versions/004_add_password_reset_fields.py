"""Add password reset fields to user table

Revision ID: 004
Revises: 003
Create Date: 2026-02-23

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user", sa.Column("password_reset_token", sa.String(length=256), nullable=True))
    op.add_column("user", sa.Column("password_reset_expires_at", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_user_password_reset_token"), "user", ["password_reset_token"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_password_reset_token"), table_name="user")
    op.drop_column("user", "password_reset_expires_at")
    op.drop_column("user", "password_reset_token")
