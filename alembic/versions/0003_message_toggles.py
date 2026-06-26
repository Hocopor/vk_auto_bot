"""message toggles on events

Revision ID: 0003_message_toggles
Revises: 0002_app_settings
Create Date: 2026-06-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0003_message_toggles"
down_revision = "0002_app_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "send_instruction",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "events",
        sa.Column(
            "send_qr",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "events",
        sa.Column(
            "send_receipt_received",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "events",
        sa.Column(
            "send_after_payment",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "events",
        sa.Column(
            "send_need_contacts",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("events", "send_need_contacts")
    op.drop_column("events", "send_after_payment")
    op.drop_column("events", "send_receipt_received")
    op.drop_column("events", "send_qr")
    op.drop_column("events", "send_instruction")
