"""add google_sheet_url to events

Revision ID: 0004_google_sheet_url
Revises: 0003_message_toggles
Create Date: 2026-06-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0004_google_sheet_url"
down_revision = "0003_message_toggles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("google_sheet_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("events", "google_sheet_url")
