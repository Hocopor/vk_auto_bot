"""add purchases.numbers_shortfall (Phase 9 overselling control)

Revision ID: 0010_numbers_shortfall
Revises: 0009_event_message_images
Create Date: 2026-06-28

"""
from alembic import op
import sqlalchemy as sa

revision = "0010_numbers_shortfall"
down_revision = "0009_event_message_images"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "purchases",
        sa.Column("numbers_shortfall", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("purchases", "numbers_shortfall")
