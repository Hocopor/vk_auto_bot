import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class PurchaseStatus(str, enum.Enum):
    pending_ocr = "pending_ocr"
    auto_confirmed = "auto_confirmed"
    manual_review = "manual_review"
    approved = "approved"
    rejected = "rejected"
    revoked = "revoked"


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index(
            "uq_event_keyword_active",
            "keyword",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    keyword: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    number_min: Mapped[int] = mapped_column(Integer, nullable=False)
    number_max: Mapped[int] = mapped_column(Integer, nullable=False)
    winners_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    msg_instruction: Mapped[str] = mapped_column(Text, nullable=False, default="")
    msg_after_payment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    msg_receipt_received: Mapped[str] = mapped_column(Text, nullable=False, default="")
    msg_need_contacts: Mapped[str] = mapped_column(Text, nullable=False, default="")
    qr_image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_confirm: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    send_instruction: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    send_qr: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    send_receipt_received: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    send_after_payment: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    send_need_contacts: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    expected_recipient: Mapped[str | None] = mapped_column(Text, nullable=True)
    sheet_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_sheet_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_attachment: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    participants: Mapped[list["Participant"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", passive_deletes=True
    )
    purchases: Mapped[list["Purchase"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", passive_deletes=True
    )
    poster_numbers: Mapped[list["PosterNumber"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", passive_deletes=True
    )


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (
        UniqueConstraint("event_id", "vk_user_id", name="uq_participant_event_vk"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vk_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vk_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    vk_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    provided_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    event: Mapped["Event"] = relationship(back_populates="participants")
    purchases: Mapped[list["Purchase"]] = relationship(
        back_populates="participant", cascade="all, delete-orphan", passive_deletes=True
    )
    poster_numbers: Mapped[list["PosterNumber"]] = relationship(
        back_populates="participant", cascade="all, delete-orphan", passive_deletes=True
    )


class Purchase(Base):
    __tablename__ = "purchases"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participant_id: Mapped[int] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    receipt_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipt_hash: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    ocr_raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    posters_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[PurchaseStatus] = mapped_column(
        Enum(PurchaseStatus, name="purchase_status", native_enum=True),
        nullable=False,
        default=PurchaseStatus.pending_ocr,
        index=True,
    )
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    receipt_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    receipt_signature: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    needs_attention: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"), index=True
    )
    numbers_assigned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    moderated_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    event: Mapped["Event"] = relationship(back_populates="purchases")
    participant: Mapped["Participant"] = relationship(back_populates="purchases")
    poster_numbers: Mapped[list["PosterNumber"]] = relationship(
        back_populates="purchase", cascade="all, delete-orphan", passive_deletes=True
    )


class PosterNumber(Base):
    __tablename__ = "poster_numbers"
    __table_args__ = (
        UniqueConstraint("event_id", "number", name="uq_poster_event_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participant_id: Mapped[int] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purchase_id: Mapped[int] = mapped_column(
        ForeignKey("purchases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    event: Mapped["Event"] = relationship(back_populates="poster_numbers")
    participant: Mapped["Participant"] = relationship(back_populates="poster_numbers")
    purchase: Mapped["Purchase"] = relationship(back_populates="poster_numbers")


class BotDialogState(Base):
    __tablename__ = "bot_dialog_state"
    __table_args__ = (
        UniqueConstraint("vk_user_id", name="uq_dialog_vk_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vk_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    event: Mapped["Event"] = relationship()


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)  # ciphertext для секретов
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
