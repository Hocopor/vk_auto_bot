from decimal import Decimal

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.admin.deps import get_session, require_login
from app.admin.main import app
from app.core import models  # noqa: F401
from app.core.db import Base
from app.core.models import Participant, PosterNumber, Purchase, PurchaseStatus
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


async def make_event(maker, **overrides):
    defaults = dict(
        name="Тест", keyword="тест", price=Decimal("250"),
        number_min=1, number_max=10, winners_count=1, auto_confirm=False,
    )
    defaults.update(overrides)
    async with maker() as session:
        event = await create_event(session, **defaults)
        await session.commit()
        return event.id


async def make_participant(maker, event_id, **overrides):
    defaults = dict(vk_user_id=111, vk_name="Иван", vk_link="https://vk.com/id111")
    defaults.update(overrides)
    async with maker() as session:
        p = Participant(event_id=event_id, **defaults)
        session.add(p)
        await session.flush()
        await session.commit()
        return p.id


async def make_purchase(maker, event_id, participant_id, **overrides):
    defaults = dict(status=PurchaseStatus.manual_review, amount=Decimal("1000"))
    defaults.update(overrides)
    async with maker() as session:
        purchase = Purchase(event_id=event_id, participant_id=participant_id, **defaults)
        session.add(purchase)
        await session.flush()
        await session.commit()
        return purchase.id


async def make_numbers(maker, event_id, participant_id, purchase_id, numbers):
    async with maker() as session:
        for n in numbers:
            session.add(
                PosterNumber(
                    event_id=event_id,
                    participant_id=participant_id,
                    purchase_id=purchase_id,
                    number=n,
                )
            )
        await session.commit()


async def test_all_mode_aggregates_one_vk_user_across_events(client, maker):
    event1_id = await make_event(maker, name="Событие 1", keyword="событие1")
    event2_id = await make_event(maker, name="Событие 2", keyword="событие2")
    await make_participant(maker, event1_id, vk_user_id=555, provided_name="Аня")
    await make_participant(maker, event2_id, vk_user_id=555, provided_name="Аня")

    resp = await client.get("/participants")
    assert resp.status_code == 200
    assert "555" in resp.text
    assert "Событие 1" in resp.text
    assert "Событие 2" in resp.text
    # одна строка, не две — считаем количество вхождений ссылки на карточку
    assert resp.text.count("/participants/vk/555") == 1


async def test_event_mode_shows_numbers(client, maker):
    event_id = await make_event(maker)
    participant_id = await make_participant(maker, event_id, vk_user_id=222)
    purchase_id = await make_purchase(maker, event_id, participant_id, status=PurchaseStatus.approved)
    await make_numbers(maker, event_id, participant_id, purchase_id, [7, 8])

    resp = await client.get("/participants", params={"event_id": event_id})
    assert resp.status_code == 200
    assert "222" in resp.text
    assert "7, 8" in resp.text


async def test_empty_event_id_renders_all_mode_not_422(client, maker):
    event_id = await make_event(maker)
    await make_participant(maker, event_id, vk_user_id=333)

    resp = await client.get("/participants", params={"event_id": ""})
    assert resp.status_code == 200
    assert "Все мероприятия" in resp.text


async def test_pagination_event_mode(client, maker):
    event_id = await make_event(maker)
    for i in range(60):
        await make_participant(maker, event_id, vk_user_id=1000 + i)

    resp1 = await client.get("/participants", params={"event_id": event_id, "page": 1})
    assert resp1.status_code == 200
    assert resp1.text.count('class="row-link"') == 50
    assert "Вперёд" in resp1.text
    assert "Назад" not in resp1.text

    resp2 = await client.get("/participants", params={"event_id": event_id, "page": 2})
    assert resp2.status_code == 200
    assert resp2.text.count('class="row-link"') == 10
    assert "Назад" in resp2.text
    assert "Вперёд" not in resp2.text


async def test_pagination_all_mode(client, maker):
    event_id = await make_event(maker)
    for i in range(60):
        await make_participant(maker, event_id, vk_user_id=2000 + i)

    resp1 = await client.get("/participants", params={"page": 1})
    assert resp1.status_code == 200
    assert resp1.text.count('class="row-link"') == 50

    resp2 = await client.get("/participants", params={"page": 2})
    assert resp2.status_code == 200
    assert resp2.text.count('class="row-link"') == 10


async def test_aggregate_card_shows_both_events(client, maker):
    event1_id = await make_event(maker, name="Розыгрыш А", keyword="а")
    event2_id = await make_event(maker, name="Розыгрыш Б", keyword="б")
    p1 = await make_participant(maker, event1_id, vk_user_id=444, provided_name="Петя")
    p2 = await make_participant(maker, event2_id, vk_user_id=444, provided_name="Петя")
    purchase1_id = await make_purchase(maker, event1_id, p1, status=PurchaseStatus.approved, amount=Decimal("300"))
    await make_numbers(maker, event1_id, p1, purchase1_id, [1, 2])
    purchase2_id = await make_purchase(maker, event2_id, p2, status=PurchaseStatus.manual_review, amount=Decimal("500"))

    resp = await client.get("/participants/vk/444")
    assert resp.status_code == 200
    assert "Розыгрыш А" in resp.text
    assert "Розыгрыш Б" in resp.text
    assert "1, 2" in resp.text
    assert f"/moderation/{purchase1_id}" in resp.text
    assert f"/moderation/{purchase2_id}" in resp.text


async def test_aggregate_card_unknown_vk_404(client, maker):
    resp = await client.get("/participants/vk/999999")
    assert resp.status_code == 404


async def test_single_card_shows_event(client, maker):
    event_id = await make_event(maker, name="Розыгрыш В", keyword="в")
    participant_id = await make_participant(maker, event_id, vk_user_id=666, provided_name="Вася")
    purchase_id = await make_purchase(maker, event_id, participant_id, amount=Decimal("250"))

    resp = await client.get(f"/participants/{participant_id}")
    assert resp.status_code == 200
    assert "Розыгрыш В" in resp.text
    assert f"/moderation/{purchase_id}" in resp.text


async def test_single_card_unknown_id_404(client, maker):
    resp = await client.get("/participants/999999")
    assert resp.status_code == 404
