from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.admin.deps import get_session, require_login
from app.admin.main import app
from app.core import models  # noqa: F401  (наполняет Base.metadata)
from app.core.db import Base
from app.core.models import Event, Participant, PosterNumber, Purchase, PurchaseStatus
from app.core.services.events import create_event


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
        "keyword": "  ПОСТЕР  ",
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


async def test_create_event(client, maker):
    resp = await client.post(
        "/events",
        data=event_form_data(),
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/events"

    async with maker() as session:
        result = await session.execute(select(Event))
        created = result.scalars().all()
        assert len(created) == 1
        event = created[0]
        assert event.keyword == "постер"
        assert event.msg_instruction
        assert event.msg_after_payment
        assert event.msg_receipt_received
        assert event.msg_need_contacts
        assert event.msg_contacts_saved


async def test_list_events(client):
    await client.post("/events", data=event_form_data(name="Список Тест"), follow_redirects=False)

    resp = await client.get("/events")
    assert resp.status_code == 200
    assert "Список Тест" in resp.text


async def test_edit_event(client, maker):
    await client.post("/events", data=event_form_data(name="До правки"), follow_redirects=False)

    async with maker() as session:
        result = await session.execute(select(Event))
        event = result.scalars().one()
        event_id = event.id

    resp = await client.post(
        f"/events/{event_id}",
        data=event_form_data(name="После правки"),
        follow_redirects=False,
    )
    assert resp.status_code == 303

    async with maker() as session:
        updated = await session.get(Event, event_id)
        assert updated.name == "После правки"


async def test_toggle_event(client, maker):
    await client.post("/events", data=event_form_data(), follow_redirects=False)

    async with maker() as session:
        result = await session.execute(select(Event))
        event = result.scalars().one()
        event_id = event.id
        was_active = event.is_active

    resp = await client.post(f"/events/{event_id}/toggle", follow_redirects=False)
    assert resp.status_code == 303

    async with maker() as session:
        updated = await session.get(Event, event_id)
        assert updated.is_active is (not was_active)


async def test_delete_event_cascade(client, maker):
    await client.post("/events", data=event_form_data(), follow_redirects=False)

    async with maker() as session:
        result = await session.execute(select(Event))
        event = result.scalars().one()
        event_id = event.id

        participant = Participant(event_id=event_id, vk_user_id=111, vk_name="Иван")
        session.add(participant)
        await session.flush()

        purchase = Purchase(
            event_id=event_id,
            participant_id=participant.id,
            status=PurchaseStatus.approved,
        )
        session.add(purchase)
        await session.flush()

        poster_number = PosterNumber(
            event_id=event_id,
            participant_id=participant.id,
            purchase_id=purchase.id,
            number=5,
        )
        session.add(poster_number)
        await session.commit()

    resp = await client.post(f"/events/{event_id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/events"

    async with maker() as session:
        assert await session.get(Event, event_id) is None

        result = await session.execute(select(Participant).where(Participant.event_id == event_id))
        assert result.scalars().all() == []

        result = await session.execute(select(Purchase).where(Purchase.event_id == event_id))
        assert result.scalars().all() == []

        result = await session.execute(select(PosterNumber).where(PosterNumber.event_id == event_id))
        assert result.scalars().all() == []


async def test_other_events_untouched_on_delete(client, maker):
    await client.post("/events", data=event_form_data(name="Первое"), follow_redirects=False)
    await client.post("/events", data=event_form_data(name="Второе", keyword="второе"), follow_redirects=False)

    async with maker() as session:
        result = await session.execute(select(Event).order_by(Event.id))
        all_events = result.scalars().all()
        assert len(all_events) == 2
        first_id, second_id = all_events[0].id, all_events[1].id

        participant = Participant(event_id=second_id, vk_user_id=222, vk_name="Пётр")
        session.add(participant)
        await session.flush()
        purchase = Purchase(
            event_id=second_id,
            participant_id=participant.id,
            status=PurchaseStatus.approved,
        )
        session.add(purchase)
        await session.flush()
        poster_number = PosterNumber(
            event_id=second_id,
            participant_id=participant.id,
            purchase_id=purchase.id,
            number=7,
        )
        session.add(poster_number)
        await session.commit()

    resp = await client.post(f"/events/{first_id}/delete", follow_redirects=False)
    assert resp.status_code == 303

    async with maker() as session:
        assert await session.get(Event, first_id) is None
        remaining = await session.get(Event, second_id)
        assert remaining is not None
        assert remaining.name == "Второе"

        result = await session.execute(select(Participant).where(Participant.event_id == second_id))
        assert len(result.scalars().all()) == 1

        result = await session.execute(select(PosterNumber).where(PosterNumber.event_id == second_id))
        assert len(result.scalars().all()) == 1


async def test_create_event_with_google_sheet_url(client, maker):
    """Event with google_sheet_url stores it correctly."""
    resp = await client.post(
        "/events",
        data=event_form_data(
            name="GS Event",
            google_sheet_url="https://docs.google.com/spreadsheets/d/xyz123/edit",
        ),
        follow_redirects=False,
    )
    assert resp.status_code == 303

    async with maker() as session:
        result = await session.execute(select(Event))
        event = result.scalars().one()
        assert event.google_sheet_url == "https://docs.google.com/spreadsheets/d/xyz123/edit"


async def test_create_event_defaults_send_need_contacts_false(maker):
    """create_event() default for send_need_contacts changed to False —
    the separate 'ask for contacts' message is no longer sent by default,
    since name+phone now arrive together with the receipt."""
    async with maker() as session:
        event = await create_event(
            session,
            name="Без контактов",
            keyword="безконтактов",
            price=Decimal("250"),
            number_min=1,
            number_max=10,
            winners_count=1,
        )
        await session.commit()
        assert event.send_need_contacts is False


async def test_create_event_via_post_has_send_need_contacts_false(client, maker):
    """The event_form.html no longer has a 'send_need_contacts' checkbox field,
    so creating an event through the admin form must result in the flag being off."""
    resp = await client.post(
        "/events",
        data=event_form_data(name="Через форму"),
        follow_redirects=False,
    )
    assert resp.status_code == 303

    async with maker() as session:
        result = await session.execute(select(Event).where(Event.name == "Через форму"))
        event = result.scalars().one()
        assert event.send_need_contacts is False


async def test_new_event_form_has_send_qr_checkbox(client):
    """Регресс: при реврайте фронта чекбокс send_qr выпал из формы, из-за чего
    каждое новое/отредактированное мероприятие сохранялось с send_qr=False и бот
    переставал слать QR. Форма обязана содержать поле send_qr."""
    resp = await client.get("/events/new")
    assert resp.status_code == 200
    assert 'name="send_qr"' in resp.text


async def test_create_event_with_send_qr(client, maker):
    """send_qr из формы сохраняется в БД (True при отмеченном чекбоксе)."""
    resp = await client.post(
        "/events",
        data=event_form_data(name="С QR", send_qr="on"),
        follow_redirects=False,
    )
    assert resp.status_code == 303

    async with maker() as session:
        result = await session.execute(select(Event).where(Event.name == "С QR"))
        event = result.scalars().one()
        assert event.send_qr is True


async def test_edit_event_google_sheet_url(client, maker, monkeypatch):
    """Editing event updates google_sheet_url (and migrates data into the
    new sheet, which we mock out here)."""
    calls = []

    async def fake_sync(session, event_id, url, *, raise_on_error=False):
        calls.append((event_id, url, raise_on_error))

    monkeypatch.setattr("app.sheets.sync.sync_event_to_sheet", fake_sync)

    await client.post("/events", data=event_form_data(), follow_redirects=False)

    async with maker() as session:
        result = await session.execute(select(Event))
        event = result.scalars().one()
        event_id = event.id

    resp = await client.post(
        f"/events/{event_id}",
        data=event_form_data(
            google_sheet_url="https://docs.google.com/spreadsheets/d/new_url/edit",
        ),
        follow_redirects=False,
    )
    assert resp.status_code == 303

    async with maker() as session:
        updated = await session.get(Event, event_id)
        assert updated.google_sheet_url == "https://docs.google.com/spreadsheets/d/new_url/edit"

    assert calls == [
        (event_id, "https://docs.google.com/spreadsheets/d/new_url/edit", True)
    ]


async def test_edit_event_sheet_url_unchanged_no_migration(client, maker, monkeypatch):
    """Сохранение мероприятия без изменения ссылки на таблицу не запускает
    миграцию (sync_event_to_sheet не вызывается)."""
    calls = []

    async def fake_sync(session, event_id, url, *, raise_on_error=False):
        calls.append((event_id, url, raise_on_error))

    monkeypatch.setattr("app.sheets.sync.sync_event_to_sheet", fake_sync)

    same_url = "https://docs.google.com/spreadsheets/d/same_url/edit"
    await client.post(
        "/events", data=event_form_data(google_sheet_url=same_url), follow_redirects=False
    )

    async with maker() as session:
        result = await session.execute(select(Event))
        event = result.scalars().one()
        event_id = event.id

    resp = await client.post(
        f"/events/{event_id}",
        data=event_form_data(name="Переименовано", google_sheet_url=same_url),
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert calls == []

    async with maker() as session:
        updated = await session.get(Event, event_id)
        assert updated.google_sheet_url == same_url


async def test_edit_event_clear_sheet_url_no_migration(client, maker, monkeypatch):
    """Очистка ссылки (Google -> своя HTML-таблица) не запускает миграцию,
    старая таблица просто отвязывается."""
    calls = []

    async def fake_sync(session, event_id, url, *, raise_on_error=False):
        calls.append((event_id, url, raise_on_error))

    monkeypatch.setattr("app.sheets.sync.sync_event_to_sheet", fake_sync)

    await client.post(
        "/events",
        data=event_form_data(
            google_sheet_url="https://docs.google.com/spreadsheets/d/old_url/edit"
        ),
        follow_redirects=False,
    )

    async with maker() as session:
        result = await session.execute(select(Event))
        event = result.scalars().one()
        event_id = event.id

    resp = await client.post(
        f"/events/{event_id}",
        data=event_form_data(google_sheet_url=""),
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert calls == []

    async with maker() as session:
        updated = await session.get(Event, event_id)
        assert updated.google_sheet_url is None


async def test_edit_event_sheet_migration_failure_blocks_save(client, maker, monkeypatch):
    """Если миграция в новую таблицу не удалась — сохранение откатывается
    целиком (включая остальные поля формы), показывается форма с ошибкой,
    в БД остаётся старая ссылка."""

    async def failing_sync(session, event_id, url, *, raise_on_error=False):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.sheets.sync.sync_event_to_sheet", failing_sync)

    old_url = "https://docs.google.com/spreadsheets/d/old_url/edit"
    await client.post(
        "/events",
        data=event_form_data(name="До ошибки", google_sheet_url=old_url),
        follow_redirects=False,
    )

    async with maker() as session:
        result = await session.execute(select(Event))
        event = result.scalars().one()
        event_id = event.id

    resp = await client.post(
        f"/events/{event_id}",
        data=event_form_data(
            name="После ошибки",
            google_sheet_url="https://docs.google.com/spreadsheets/d/broken_url/edit",
        ),
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "не удалось записать" in resp.text.lower()

    async with maker() as session:
        updated = await session.get(Event, event_id)
        assert updated.google_sheet_url == old_url
        assert updated.name == "До ошибки"


async def test_create_duplicate_active_keyword_blocked(client, maker):
    """Создание мероприятия с кодовым словом, занятым другим активным
    мероприятием, не должно приводить к 500 — должна вернуться форма с
    понятной ошибкой."""
    await client.post("/events", data=event_form_data(), follow_redirects=False)

    resp = await client.post(
        "/events",
        data=event_form_data(name="Дубль", keyword="постер"),
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "уже используется" in resp.text
    assert "Розыгрыш постеров" in resp.text

    async with maker() as session:
        result = await session.execute(select(Event))
        assert len(result.scalars().all()) == 1


async def test_update_to_duplicate_active_keyword_blocked(client, maker):
    """Редактирование мероприятия с попыткой занять кодовое слово другого
    активного мероприятия должно вернуть понятную ошибку, а не 500."""
    await client.post(
        "/events", data=event_form_data(name="Первое", keyword="постер"), follow_redirects=False
    )
    await client.post(
        "/events", data=event_form_data(name="Второе", keyword="второе"), follow_redirects=False
    )

    async with maker() as session:
        result = await session.execute(select(Event).order_by(Event.id))
        all_events = result.scalars().all()
        second_id = all_events[1].id

    resp = await client.post(
        f"/events/{second_id}",
        data=event_form_data(name="Второе", keyword="постер"),
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "уже используется" in resp.text

    async with maker() as session:
        updated = await session.get(Event, second_id)
        assert updated.keyword == "второе"


async def test_update_same_event_keeps_keyword_ok(client, maker):
    """Сохранение мероприятия со своим же текущим кодовым словом не должно
    считаться конфликтом."""
    await client.post(
        "/events", data=event_form_data(name="Первое", keyword="постер"), follow_redirects=False
    )

    async with maker() as session:
        result = await session.execute(select(Event))
        event = result.scalars().one()
        event_id = event.id

    resp = await client.post(
        f"/events/{event_id}",
        data=event_form_data(name="Переименовано", keyword="постер"),
        follow_redirects=False,
    )
    assert resp.status_code == 303

    async with maker() as session:
        updated = await session.get(Event, event_id)
        assert updated.name == "Переименовано"


async def test_new_event_form_has_contacts_saved_fields(client):
    """Форма должна содержать поля msg_contacts_saved и send_contacts_saved
    (этап 8.4 — новое сообщение «данные приняты»)."""
    resp = await client.get("/events/new")
    assert resp.status_code == 200
    assert 'name="send_contacts_saved"' in resp.text
    assert 'name="msg_contacts_saved"' in resp.text


async def test_create_event_with_contacts_saved_fields(client, maker):
    """Создание мероприятия с явным текстом/тумблером msg_contacts_saved сохраняет их."""
    resp = await client.post(
        "/events",
        data=event_form_data(
            name="С контактами",
            msg_contacts_saved="Спасибо за данные!",
            send_contacts_saved="on",
        ),
        follow_redirects=False,
    )
    assert resp.status_code == 303

    async with maker() as session:
        result = await session.execute(select(Event).where(Event.name == "С контактами"))
        event = result.scalars().one()
        assert event.msg_contacts_saved == "Спасибо за данные!"
        assert event.send_contacts_saved is True


async def test_update_event_cannot_shrink_range_below_assigned_numbers(client, maker):
    """Фаза 9: нельзя сузить диапазон ниже уже присвоенных номеров — форма 400,
    диапазон не меняется."""
    async with maker() as session:
        event = await create_event(
            session, name="Диапазон", keyword="диап", price=Decimal("250"),
            number_min=1, number_max=100, winners_count=1,
        )
        participant = Participant(event_id=event.id, vk_user_id=1, provided_name="Иван")
        session.add(participant)
        await session.flush()
        purchase = Purchase(
            event_id=event.id, participant_id=participant.id, amount=Decimal("500"),
            posters_count=1, status=PurchaseStatus.approved, numbers_assigned=True,
        )
        session.add(purchase)
        await session.flush()
        session.add(PosterNumber(
            event_id=event.id, participant_id=participant.id, purchase_id=purchase.id, number=50,
        ))
        await session.commit()
        event_id = event.id

    resp = await client.post(
        f"/events/{event_id}",
        data=event_form_data(name="Диапазон", keyword="диап", number_min="1", number_max="10"),
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "сузить диапазон" in resp.text.lower()

    async with maker() as session:
        refreshed = await session.get(Event, event_id)
        assert refreshed.number_max == 100  # диапазон не изменился


async def test_events_list_shows_exhausted_badge(client, maker):
    """Фаза 9: в списке мероприятий при исчерпании ёмкости виден бейдж."""
    async with maker() as session:
        event = await create_event(
            session, name="Полное", keyword="полн", price=Decimal("250"),
            number_min=1, number_max=1, winners_count=1,
        )
        participant = Participant(event_id=event.id, vk_user_id=1, provided_name="Иван")
        session.add(participant)
        await session.flush()
        purchase = Purchase(
            event_id=event.id, participant_id=participant.id, amount=Decimal("250"),
            posters_count=1, status=PurchaseStatus.approved, numbers_assigned=False,
        )
        session.add(purchase)
        await session.commit()

    resp = await client.get("/events")
    assert resp.status_code == 200
    assert "ИСЧЕРПАНО" in resp.text
