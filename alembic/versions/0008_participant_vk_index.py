"""index participants.vk_user_id for aggregation across events

Revision ID: 0008_participant_vk_index
Revises: 0007_dialog_fsm_contacts
Create Date: 2026-06-27
"""
from alembic import op

revision = "0008_participant_vk_index"
down_revision = "0007_dialog_fsm_contacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_participants_vk_user_id", "participants", ["vk_user_id"])


def downgrade() -> None:
    op.drop_index("ix_participants_vk_user_id", table_name="participants")
