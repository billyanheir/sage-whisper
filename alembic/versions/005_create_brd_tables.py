"""Create BRD and BRD requirement tables

Revision ID: 005
Revises: 004
Create Date: 2026-02-23

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brd",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("transcript_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="generating"),
        sa.Column("project_context", sa.Text(), nullable=True),
        sa.Column("github_repo_url", sa.String(length=1024), nullable=True),
        sa.Column("parent_brd_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finalized_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["transcript_id"], ["transcript.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["parent_brd_id"], ["brd.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_brd_transcript_id"), "brd", ["transcript_id"], unique=False)
    op.create_index(op.f("ix_brd_user_id"), "brd", ["user_id"], unique=False)

    op.create_table(
        "brd_requirement",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("brd_id", sa.Integer(), nullable=False),
        sa.Column("requirement_text", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=False, server_default="General"),
        sa.Column("priority", sa.String(length=32), nullable=False, server_default="should"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["brd_id"], ["brd.id"]),
        sa.ForeignKeyConstraint(["parent_id"], ["brd_requirement.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_brd_requirement_brd_id"), "brd_requirement", ["brd_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_brd_requirement_brd_id"), table_name="brd_requirement")
    op.drop_table("brd_requirement")
    op.drop_index(op.f("ix_brd_user_id"), table_name="brd")
    op.drop_index(op.f("ix_brd_transcript_id"), table_name="brd")
    op.drop_table("brd")
