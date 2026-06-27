"""add bot dialog stage and contacts-saved fields for FSM flow

Revision ID: 0007_dialog_fsm_contacts
Revises: 0006_receipt_date_abuse
Create Date: 2026-06-27

"""
from alembic import op
import sqlalchemy as sa

revision = "0007_dialog_fsm_contacts"
down_revision = "0006_receipt_date_abuse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bot_dialog_state",
        sa.Column(
            "stage",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'awaiting_receipt'"),
        ),
    )
    op.add_column("participants", sa.Column("public_name", sa.Text(), nullable=True))
    op.add_column("participants", sa.Column("vk_first_name", sa.Text(), nullable=True))
    op.add_column(
        "events",
        sa.Column(
            "msg_contacts_saved",
            sa.Text(),
            nullable=False,
            server_default=sa.text(
                "'Спасибо! Ваши данные приняты. Как только оплата подтвердится, "
                "я пришлю ваши номера участника.'"
            ),
        ),
    )
    op.add_column(
        "events",
        sa.Column(
            "send_contacts_saved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("events", "send_contacts_saved")
    op.drop_column("events", "msg_contacts_saved")
    op.drop_column("participants", "vk_first_name")
    op.drop_column("participants", "public_name")
    op.drop_column("bot_dialog_state", "stage")
