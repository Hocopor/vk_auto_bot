"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-25

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


purchase_status_enum = sa.Enum(
    "pending_ocr",
    "auto_confirmed",
    "manual_review",
    "approved",
    "rejected",
    "revoked",
    name="purchase_status",
)


def upgrade() -> None:
    # --- events ---
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("keyword", sa.Text(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("number_min", sa.Integer(), nullable=False),
        sa.Column("number_max", sa.Integer(), nullable=False),
        sa.Column(
            "winners_count", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "msg_instruction", sa.Text(), nullable=False, server_default=sa.text("''")
        ),
        sa.Column(
            "msg_after_payment",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "msg_receipt_received",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "msg_need_contacts",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column("qr_image_path", sa.Text(), nullable=True),
        sa.Column(
            "auto_confirm",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("expected_recipient", sa.Text(), nullable=True),
        sa.Column("sheet_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_events_keyword", "events", ["keyword"])
    op.create_index(
        "uq_event_keyword_active",
        "events",
        ["keyword"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    # --- participants ---
    op.create_table(
        "participants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("vk_user_id", sa.BigInteger(), nullable=False),
        sa.Column("vk_name", sa.Text(), nullable=True),
        sa.Column("vk_link", sa.Text(), nullable=True),
        sa.Column("provided_name", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("event_id", "vk_user_id", name="uq_participant_event_vk"),
    )
    op.create_index("ix_participants_event_id", "participants", ["event_id"])

    # --- purchases ---
    op.create_table(
        "purchases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "participant_id",
            sa.Integer(),
            sa.ForeignKey("participants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("receipt_file_path", sa.Text(), nullable=True),
        sa.Column("receipt_hash", sa.Text(), nullable=True),
        sa.Column("ocr_raw_text", sa.Text(), nullable=True),
        sa.Column("ocr_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("posters_count", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            purchase_status_enum,
            nullable=False,
            server_default=sa.text("'pending_ocr'"),
        ),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column(
            "numbers_assigned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("moderated_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_purchases_event_id", "purchases", ["event_id"])
    op.create_index("ix_purchases_participant_id", "purchases", ["participant_id"])
    op.create_index("ix_purchases_receipt_hash", "purchases", ["receipt_hash"])
    op.create_index("ix_purchases_status", "purchases", ["status"])
    op.create_index(
        "ix_purchases_numbers_assigned", "purchases", ["numbers_assigned"]
    )

    # --- poster_numbers ---
    op.create_table(
        "poster_numbers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "participant_id",
            sa.Integer(),
            sa.ForeignKey("participants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "purchase_id",
            sa.Integer(),
            sa.ForeignKey("purchases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("event_id", "number", name="uq_poster_event_number"),
    )
    op.create_index("ix_poster_numbers_event_id", "poster_numbers", ["event_id"])
    op.create_index(
        "ix_poster_numbers_participant_id", "poster_numbers", ["participant_id"]
    )
    op.create_index(
        "ix_poster_numbers_purchase_id", "poster_numbers", ["purchase_id"]
    )

    # --- bot_dialog_state ---
    op.create_table(
        "bot_dialog_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vk_user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("vk_user_id", name="uq_dialog_vk_user"),
    )
    op.create_index(
        "ix_bot_dialog_state_vk_user_id", "bot_dialog_state", ["vk_user_id"]
    )
    op.create_index(
        "ix_bot_dialog_state_event_id", "bot_dialog_state", ["event_id"]
    )


def downgrade() -> None:
    op.drop_table("bot_dialog_state")
    op.drop_table("poster_numbers")
    op.drop_table("purchases")
    op.drop_table("participants")
    op.drop_table("events")
    op.execute("DROP TYPE IF EXISTS purchase_status")
