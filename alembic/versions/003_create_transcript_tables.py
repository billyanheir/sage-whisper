"""Create transcript and transcript_segment tables

Revision ID: 003
Revises: 002
Create Date: 2026-02-23

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transcript",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("voice_note_id", sa.Integer(), sa.ForeignKey("voice_note.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("full_text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("model_size", sa.String(length=32), nullable=False),
        sa.Column("processing_time_seconds", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_transcript_voice_note_id"), "transcript", ["voice_note_id"], unique=True)
    op.create_index(op.f("ix_transcript_user_id"), "transcript", ["user_id"])

    op.create_table(
        "transcript_segment",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("transcript_id", sa.Integer(), sa.ForeignKey("transcript.id"), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_transcript_segment_transcript_id"), "transcript_segment", ["transcript_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_transcript_segment_transcript_id"), table_name="transcript_segment")
    op.drop_table("transcript_segment")
    op.drop_index(op.f("ix_transcript_user_id"), table_name="transcript")
    op.drop_index(op.f("ix_transcript_voice_note_id"), table_name="transcript")
    op.drop_table("transcript")
