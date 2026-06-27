"""add receipt_date, receipt_signature, needs_attention to purchases

Revision ID: 0006_receipt_date_abuse
Revises: 0005_qr_attachment
Create Date: 2026-06-27

"""
from alembic import op
import sqlalchemy as sa

revision = "0006_receipt_date_abuse"
down_revision = "0005_qr_attachment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchases", sa.Column("receipt_date", sa.Date(), nullable=True))
    op.add_column("purchases", sa.Column("receipt_signature", sa.Text(), nullable=True))
    op.add_column(
        "purchases",
        sa.Column(
            "needs_attention",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index("ix_purchases_receipt_signature", "purchases", ["receipt_signature"])
    op.create_index("ix_purchases_needs_attention", "purchases", ["needs_attention"])


def downgrade() -> None:
    op.drop_index("ix_purchases_needs_attention", table_name="purchases")
    op.drop_index("ix_purchases_receipt_signature", table_name="purchases")
    op.drop_column("purchases", "needs_attention")
    op.drop_column("purchases", "receipt_signature")
    op.drop_column("purchases", "receipt_date")
