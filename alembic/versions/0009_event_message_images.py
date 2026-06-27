"""add event_message_images table

Revision ID: 0009_event_message_images
Revises: 0008_participant_vk_index
Create Date: 2026-06-28

"""
from alembic import op
import sqlalchemy as sa

revision = "0009_event_message_images"
down_revision = "0008_participant_vk_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_message_images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message_key", sa.Text(), nullable=False),
        sa.Column("image_path", sa.Text(), nullable=False),
        sa.Column("attachment", sa.Text(), nullable=True),
        sa.Column("attachment_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("event_id", "message_key", name="uq_msg_image_event_key"),
    )
    op.create_index(
        "ix_event_message_images_event_id",
        "event_message_images",
        ["event_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_event_message_images_event_id", table_name="event_message_images")
    op.drop_table("event_message_images")
