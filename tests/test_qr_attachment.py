"""Тесты для app.bot.handlers.resolve_qr_attachment — кэш/загрузка/ошибка QR."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.bot.handlers import resolve_qr_attachment
from app.core import models  # noqa: F401  (наполняет Base.metadata)
from app.core.db import Base
from app.core.services.events import create_event


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


class FakeUploader:
    """Фейковый PhotoMessageUploader: накапливает вызовы, возвращает/кидает заданное."""

    calls: list = []

    def __init__(self, api):
        self.api = api

    async def upload(self, file_source: str):
        FakeUploader.calls.append(file_source)
        if FakeUploader.exception is not None:
            raise FakeUploader.exception
        return FakeUploader.result


@pytest.fixture(autouse=True)
def _reset_fake_uploader():
    FakeUploader.calls = []
    FakeUploader.result = None
    FakeUploader.exception = None
    yield


async def _make_event(session, **kwargs):
    defaults = dict(
        name="Розыгрыш",
        keyword="роза",
        price=Decimal("250"),
        number_min=1,
        number_max=10,
    )
    defaults.update(kwargs)
    event = await create_event(session, **defaults)
    await session.commit()
    return event


async def test_cache_used_when_qr_attachment_already_set(session):
    event = await _make_event(session, send_qr=True)
    event.qr_attachment = "photo-1_2_x"
    await session.commit()

    result = await resolve_qr_attachment(event, upload_api=object(), uploader_cls=FakeUploader)

    assert result == "photo-1_2_x"
    assert FakeUploader.calls == []


async def test_successful_upload_is_cached(session, tmp_path):
    qr_path = tmp_path / "qr.png"
    qr_path.write_bytes(b"fake-image-bytes")

    event = await _make_event(session, send_qr=True, qr_image_path=str(qr_path))
    FakeUploader.result = "photo-9_9_z"

    result = await resolve_qr_attachment(event, upload_api=object(), uploader_cls=FakeUploader)

    assert result == "photo-9_9_z"
    assert event.qr_attachment == "photo-9_9_z"
    assert event.qr_last_error is None
    assert FakeUploader.calls == [str(qr_path)]


async def test_send_qr_false_returns_none(session, tmp_path):
    qr_path = tmp_path / "qr.png"
    qr_path.write_bytes(b"fake-image-bytes")

    event = await _make_event(session, send_qr=False, qr_image_path=str(qr_path))

    result = await resolve_qr_attachment(event, upload_api=object(), uploader_cls=FakeUploader)

    assert result is None
    assert FakeUploader.calls == []


async def test_missing_file_returns_none(session, tmp_path):
    missing_path = str(tmp_path / "does_not_exist.png")

    event = await _make_event(session, send_qr=True, qr_image_path=missing_path)

    result = await resolve_qr_attachment(event, upload_api=object(), uploader_cls=FakeUploader)

    assert result is None
    assert FakeUploader.calls == []


async def test_upload_failure_records_error_and_retries(session, tmp_path):
    qr_path = tmp_path / "qr.png"
    qr_path.write_bytes(b"fake-image-bytes")

    event = await _make_event(session, send_qr=True, qr_image_path=str(qr_path))
    FakeUploader.exception = RuntimeError("boom")

    result = await resolve_qr_attachment(
        event, upload_api=object(), uploader_cls=FakeUploader, retries=3
    )

    assert result is None
    assert event.qr_last_error is not None
    assert "RuntimeError" in event.qr_last_error
    assert len(FakeUploader.calls) == 3
