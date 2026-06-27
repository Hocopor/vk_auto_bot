"""Тесты для картинок-вложений к сообщениям бота (EventMessageImage).

Покрывает: схему БД, роуты админки (upload/replace/delete/preview),
resolve_message_attachment (кэш/ошибка/retry), воркер (attachment в
after_payment), каскадное удаление файлов при удалении события.
"""

import os
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.admin.deps import get_session, require_login
from app.admin.main import app
from app.bot.handlers import resolve_message_attachment
from app.bot.worker import process_pending
from app.core import models  # noqa: F401  (наполняет Base.metadata)
from app.core.config import settings
from app.core.db import Base
from app.core.models import Event, EventMessageImage, Participant, Purchase, PurchaseStatus
from app.core.services.events import create_event, delete_event


# --------------------------------------------------------------------------
# Фикстуры (стиль как в test_qr_attachment.py / test_admin_events.py)
# --------------------------------------------------------------------------


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
def maker(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def client(maker):
    async def _get_session_override():
        async with maker() as session:
            yield session

    async def _require_login_override():
        return "admin"

    app.dependency_overrides[get_session] = _get_session_override
    app.dependency_overrides[require_login] = _require_login_override

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(require_login, None)


def event_form_data(**overrides):
    data = {
        "name": "Розыгрыш постеров",
        "keyword": "постер",
        "price": "250",
        "number_min": "1",
        "number_max": "100",
        "winners_count": "1",
        "starts_at": "",
        "ends_at": "",
        "expected_recipient": "",
        "msg_instruction": "",
        "msg_after_payment": "",
        "msg_receipt_received": "",
        "msg_need_contacts": "",
        "msg_contacts_saved": "",
        "google_sheet_url": "",
    }
    data.update(overrides)
    return data


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


class FakeUploader:
    """Фейковый PhotoMessageUploader (как в test_qr_attachment.py)."""

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


# --------------------------------------------------------------------------
# 1. Схема
# --------------------------------------------------------------------------


async def test_table_created_and_unique_constraint_holds(session):
    event = await _make_event(session)
    session.add(
        EventMessageImage(
            event_id=event.id, message_key="receipt_received", image_path="/x/a.png"
        )
    )
    await session.commit()

    session.add(
        EventMessageImage(
            event_id=event.id, message_key="receipt_received", image_path="/x/b.png"
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


# --------------------------------------------------------------------------
# 2-4. Роуты: upload / replace / delete
# --------------------------------------------------------------------------


async def test_create_event_with_message_image_uploads_file(client, maker, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "message_images_dir", str(tmp_path))

    resp = await client.post(
        "/events",
        data=event_form_data(name="С картинкой"),
        files={"image_receipt_received": ("a.png", b"some-bytes-content", "image/png")},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    async with maker() as session:
        event = (
            await session.execute(select(Event).where(Event.name == "С картинкой"))
        ).scalars().one()
        row = (
            await session.execute(
                select(EventMessageImage).where(
                    EventMessageImage.event_id == event.id,
                    EventMessageImage.message_key == "receipt_received",
                )
            )
        ).scalar_one()
        assert os.path.exists(row.image_path)
        with open(row.image_path, "rb") as f:
            assert f.read() == b"some-bytes-content"


async def test_replace_message_image_removes_old_file(client, maker, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "message_images_dir", str(tmp_path))

    await client.post(
        "/events",
        data=event_form_data(name="Замена"),
        files={"image_contacts_saved": ("first.png", b"first-bytes", "image/png")},
        follow_redirects=False,
    )

    async with maker() as session:
        event = (
            await session.execute(select(Event).where(Event.name == "Замена"))
        ).scalars().one()
        event_id = event.id
        row = (
            await session.execute(
                select(EventMessageImage).where(
                    EventMessageImage.event_id == event_id,
                    EventMessageImage.message_key == "contacts_saved",
                )
            )
        ).scalar_one()
        old_path = row.image_path
        assert os.path.exists(old_path)

    resp = await client.post(
        f"/events/{event_id}",
        data=event_form_data(name="Замена"),
        files={"image_contacts_saved": ("second.png", b"second-bytes", "image/png")},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    assert not os.path.exists(old_path)

    async with maker() as session:
        row = (
            await session.execute(
                select(EventMessageImage).where(
                    EventMessageImage.event_id == event_id,
                    EventMessageImage.message_key == "contacts_saved",
                )
            )
        ).scalar_one()
        assert row.image_path != old_path
        assert os.path.exists(row.image_path)
        assert row.attachment is None
        with open(row.image_path, "rb") as f:
            assert f.read() == b"second-bytes"


async def test_delete_message_image_via_checkbox(client, maker, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "message_images_dir", str(tmp_path))

    await client.post(
        "/events",
        data=event_form_data(name="Удаление"),
        files={"image_after_payment": ("a.png", b"bytes-x", "image/png")},
        follow_redirects=False,
    )

    async with maker() as session:
        event = (
            await session.execute(select(Event).where(Event.name == "Удаление"))
        ).scalars().one()
        event_id = event.id
        row = (
            await session.execute(
                select(EventMessageImage).where(
                    EventMessageImage.event_id == event_id,
                    EventMessageImage.message_key == "after_payment",
                )
            )
        ).scalar_one()
        old_path = row.image_path
        assert os.path.exists(old_path)

    resp = await client.post(
        f"/events/{event_id}",
        data=event_form_data(name="Удаление", image_after_payment_delete="on"),
        follow_redirects=False,
    )
    assert resp.status_code == 303

    assert not os.path.exists(old_path)

    async with maker() as session:
        row = (
            await session.execute(
                select(EventMessageImage).where(
                    EventMessageImage.event_id == event_id,
                    EventMessageImage.message_key == "after_payment",
                )
            )
        ).scalar_one_or_none()
        assert row is None


# --------------------------------------------------------------------------
# 5. Превью-роут
# --------------------------------------------------------------------------


async def test_message_image_preview_route_200_and_404(client, maker, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "message_images_dir", str(tmp_path))

    await client.post(
        "/events",
        data=event_form_data(name="Превью"),
        files={"image_receipt_received": ("a.png", b"preview-bytes", "image/png")},
        follow_redirects=False,
    )

    async with maker() as session:
        event = (
            await session.execute(select(Event).where(Event.name == "Превью"))
        ).scalars().one()
        event_id = event.id

    resp = await client.get(f"/events/{event_id}/message-image/receipt_received")
    assert resp.status_code == 200

    resp = await client.get(f"/events/{event_id}/message-image/contacts_saved")
    assert resp.status_code == 404

    resp = await client.get(f"/events/999999/message-image/receipt_received")
    assert resp.status_code == 404


# --------------------------------------------------------------------------
# 6. resolve_message_attachment
# --------------------------------------------------------------------------


async def test_resolve_no_row_returns_none(session):
    event = await _make_event(session)

    result = await resolve_message_attachment(
        session, event.id, "receipt_received", upload_api=object(), uploader_cls=FakeUploader
    )

    assert result is None
    assert FakeUploader.calls == []


async def test_resolve_cached_attachment_not_reuploaded(session):
    event = await _make_event(session)
    row = EventMessageImage(
        event_id=event.id,
        message_key="receipt_received",
        image_path="/does/not/matter.png",
        attachment="photo-1_2_x",
    )
    session.add(row)
    await session.commit()

    result = await resolve_message_attachment(
        session, event.id, "receipt_received", upload_api=object(), uploader_cls=FakeUploader
    )

    assert result == "photo-1_2_x"
    assert FakeUploader.calls == []


async def test_resolve_successful_upload_is_cached(session, tmp_path):
    event = await _make_event(session)
    img_path = tmp_path / "img.png"
    img_path.write_bytes(b"fake-image-bytes")
    row = EventMessageImage(
        event_id=event.id, message_key="contacts_saved", image_path=str(img_path)
    )
    session.add(row)
    await session.commit()

    FakeUploader.result = "photo-9_9_z"

    result = await resolve_message_attachment(
        session, event.id, "contacts_saved", upload_api=object(), uploader_cls=FakeUploader
    )

    assert result == "photo-9_9_z"
    assert FakeUploader.calls == [str(img_path)]

    refreshed = (
        await session.execute(
            select(EventMessageImage).where(
                EventMessageImage.event_id == event.id,
                EventMessageImage.message_key == "contacts_saved",
            )
        )
    ).scalar_one()
    assert refreshed.attachment == "photo-9_9_z"


async def test_resolve_upload_failure_records_error(session, tmp_path):
    event = await _make_event(session)
    img_path = tmp_path / "img.png"
    img_path.write_bytes(b"fake-image-bytes")
    row = EventMessageImage(
        event_id=event.id, message_key="after_payment", image_path=str(img_path)
    )
    session.add(row)
    await session.commit()

    FakeUploader.exception = RuntimeError("boom")

    result = await resolve_message_attachment(
        session, event.id, "after_payment", upload_api=object(), uploader_cls=FakeUploader, retries=3
    )

    assert result is None
    refreshed = (
        await session.execute(
            select(EventMessageImage).where(
                EventMessageImage.event_id == event.id,
                EventMessageImage.message_key == "after_payment",
            )
        )
    ).scalar_one()
    assert refreshed.attachment_error
    assert "RuntimeError" in refreshed.attachment_error
    assert len(FakeUploader.calls) == 3


# --------------------------------------------------------------------------
# 7. Воркер: attachment в after_payment
# --------------------------------------------------------------------------


async def test_worker_sends_attachment_when_upload_api_set(session, tmp_path, monkeypatch):
    event = Event(
        name="Розыгрыш",
        keyword="роза",
        is_active=True,
        price=Decimal("250"),
        number_min=1,
        number_max=10,
        winners_count=1,
        msg_after_payment="Номера: {numbers}",
        send_after_payment=True,
        send_need_contacts=False,
    )
    session.add(event)
    await session.flush()

    img_path = tmp_path / "img.png"
    img_path.write_bytes(b"fake-image-bytes")
    session.add(
        EventMessageImage(
            event_id=event.id, message_key="after_payment", image_path=str(img_path)
        )
    )

    participant = Participant(
        event_id=event.id, vk_user_id=555, provided_name="Иван", phone="+79001234567"
    )
    session.add(participant)
    await session.flush()
    purchase = Purchase(
        event_id=event.id,
        participant_id=participant.id,
        amount=Decimal("250"),
        posters_count=1,
        status=PurchaseStatus.approved,
        numbers_assigned=False,
    )
    session.add(purchase)
    await session.commit()

    FakeUploader.result = "photo-5_5_y"

    async def fake_resolve(sess, event_id, message_key, upload_api):
        return await resolve_message_attachment(
            sess, event_id, message_key, upload_api, uploader_cls=FakeUploader
        )

    monkeypatch.setattr("app.bot.handlers.resolve_message_attachment", fake_resolve)

    sent = []

    async def send_message(vk_user_id, text, attachment=None):
        sent.append((vk_user_id, text, attachment))

    processed = await process_pending(session, send_message=send_message, upload_api=object())

    assert processed == 1
    assert len(sent) == 1
    assert sent[0][2] == "photo-5_5_y"


async def test_worker_no_upload_api_means_no_attachment(session):
    event = Event(
        name="Розыгрыш",
        keyword="роза2",
        is_active=True,
        price=Decimal("250"),
        number_min=1,
        number_max=10,
        winners_count=1,
        msg_after_payment="Номера: {numbers}",
        send_after_payment=True,
        send_need_contacts=False,
    )
    session.add(event)
    await session.flush()

    session.add(
        EventMessageImage(
            event_id=event.id, message_key="after_payment", image_path="/some/path.png"
        )
    )

    participant = Participant(
        event_id=event.id, vk_user_id=556, provided_name="Пётр", phone="+79001234568"
    )
    session.add(participant)
    await session.flush()
    purchase = Purchase(
        event_id=event.id,
        participant_id=participant.id,
        amount=Decimal("250"),
        posters_count=1,
        status=PurchaseStatus.approved,
        numbers_assigned=False,
    )
    session.add(purchase)
    await session.commit()

    sent = []

    async def send_message(vk_user_id, text, attachment=None):
        sent.append((vk_user_id, text, attachment))

    processed = await process_pending(session, send_message=send_message, upload_api=None)

    assert processed == 1
    assert len(sent) == 1
    assert sent[0][2] is None


# --------------------------------------------------------------------------
# 8. delete_event: каскадное удаление файлов
# --------------------------------------------------------------------------


async def test_delete_event_removes_message_image_files(client, maker, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "message_images_dir", str(tmp_path))

    await client.post(
        "/events",
        data=event_form_data(name="Удаление события"),
        files={
            "image_receipt_received": ("a.png", b"bytes-a", "image/png"),
            "image_contacts_saved": ("b.png", b"bytes-b", "image/png"),
        },
        follow_redirects=False,
    )

    async with maker() as session:
        event = (
            await session.execute(select(Event).where(Event.name == "Удаление события"))
        ).scalars().one()
        event_id = event.id
        rows = (
            await session.execute(
                select(EventMessageImage).where(EventMessageImage.event_id == event_id)
            )
        ).scalars().all()
        paths = [r.image_path for r in rows]
        assert len(paths) == 2
        assert all(os.path.exists(p) for p in paths)

    resp = await client.post(f"/events/{event_id}/delete", follow_redirects=False)
    assert resp.status_code == 303

    assert all(not os.path.exists(p) for p in paths)

    async with maker() as session:
        remaining = (
            await session.execute(
                select(EventMessageImage).where(EventMessageImage.event_id == event_id)
            )
        ).scalars().all()
        assert remaining == []


async def test_delete_event_service_cascades_message_images(session, tmp_path):
    """delete_event() (сервисный слой) каскадно удаляет EventMessageImage в БД."""
    event = await _make_event(session)
    img_path = tmp_path / "img.png"
    img_path.write_bytes(b"abc")
    session.add(
        EventMessageImage(event_id=event.id, message_key="receipt_received", image_path=str(img_path))
    )
    await session.commit()

    await delete_event(session, event.id)
    await session.commit()

    remaining = (
        await session.execute(
            select(EventMessageImage).where(EventMessageImage.event_id == event.id)
        )
    ).scalars().all()
    assert remaining == []
