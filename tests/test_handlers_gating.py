"""Тесты гейтинга отправки сообщений в app.bot.handlers по тумблерам события."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.bot import dialog, handlers
from app.core import models  # noqa: F401  (наполняет Base.metadata)
from app.core.db import Base
from app.core.services.events import create_event
from app.ocr import recognize as ocr_recognize


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


class FakeMessage:
    def __init__(self, text=""):
        self.text = text
        self.from_id = 555
        self.answers: list[tuple[str, object]] = []

    async def answer(self, text="", attachment=None):
        self.answers.append((text, attachment))


@pytest.fixture(autouse=True)
def _no_tesseract(monkeypatch):
    # На CI/локально Tesseract может отсутствовать — гарантированно отключаем OCR-ветку,
    # чтобы тест не зависел от окружения.
    monkeypatch.setattr(ocr_recognize, "tesseract_available", lambda: False)


@pytest.fixture(autouse=True)
def _no_download(monkeypatch):
    async def _fake_download(url: str) -> bytes:
        return b"fake-receipt-bytes"

    monkeypatch.setattr(handlers, "_download", _fake_download)


async def test_receipt_received_message_sent_when_enabled(session, tmp_path, monkeypatch):
    monkeypatch.setattr(
        __import__("app.core.config", fromlist=["settings"]).settings,
        "receipts_dir",
        str(tmp_path),
    )
    event = await create_event(
        session,
        name="Розыгрыш",
        keyword="роза",
        price=Decimal("250"),
        number_min=1,
        number_max=10,
        msg_receipt_received="Чек получен",
        send_receipt_received=True,
    )
    await session.commit()
    await dialog.set_dialog(session, 555, event.id)
    await session.commit()

    message = FakeMessage()
    await handlers._handle_receipt(
        bot=None,
        message=message,
        session=session,
        user_id=555,
        vk_name="Иван",
        vk_link="https://vk.com/id555",
        vk_first_name="Иван",
        attachment_info=("http://example.com/receipt.jpg", "jpg"),
    )

    assert len(message.answers) == 1
    assert "Чек получен" in message.answers[0][0]


async def test_receipt_received_message_not_sent_when_disabled(session, tmp_path, monkeypatch):
    monkeypatch.setattr(
        __import__("app.core.config", fromlist=["settings"]).settings,
        "receipts_dir",
        str(tmp_path),
    )
    event = await create_event(
        session,
        name="Розыгрыш",
        keyword="роза",
        price=Decimal("250"),
        number_min=1,
        number_max=10,
        msg_receipt_received="Чек получен",
        send_receipt_received=False,
    )
    await session.commit()
    await dialog.set_dialog(session, 555, event.id)
    await session.commit()

    message = FakeMessage()
    await handlers._handle_receipt(
        bot=None,
        message=message,
        session=session,
        user_id=555,
        vk_name="Иван",
        vk_link="https://vk.com/id555",
        vk_first_name="Иван",
        attachment_info=("http://example.com/receipt.jpg", "jpg"),
    )

    assert message.answers == []
