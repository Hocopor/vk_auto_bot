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


async def test_edit_event_google_sheet_url(client, maker):
    """Editing event updates google_sheet_url."""
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
