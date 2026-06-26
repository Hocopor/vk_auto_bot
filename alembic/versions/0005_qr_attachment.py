"""add qr_attachment and qr_last_error to events

Revision ID: 0005_qr_attachment
Revises: 0004_google_sheet_url
Create Date: 2026-06-27

"""
from alembic import op
import sqlalchemy as sa

revision = "0005_qr_attachment"
down_revision = "0004_google_sheet_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("qr_attachment", sa.Text(), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("qr_last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("events", "qr_last_error")
    op.drop_column("events", "qr_attachment")
