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


async def make_poster_number(maker, event_id, participant_id, purchase_id, number):
    async with maker() as session:
        pn = PosterNumber(
            event_id=event_id,
            participant_id=participant_id,
            purchase_id=purchase_id,
            number=number,
        )
        session.add(pn)
        await session.flush()
        await session.commit()
        return pn.id


async def test_participants_list_shows_numbers(client, maker):
    event_id = await make_event(maker)
    participant_id = await make_participant(
        maker, event_id, provided_name="Иван Тестов"
    )
    purchase_id = await make_purchase(
        maker, event_id, participant_id, status=PurchaseStatus.approved
    )
    for n in (5, 12, 7):
        await make_poster_number(maker, event_id, participant_id, purchase_id, n)

    resp = await client.get("/participants", params={"event_id": event_id})
    assert resp.status_code == 200
    assert "Иван Тестов" in resp.text
    assert "5" in resp.text
    assert "12" in resp.text
    assert "7" in resp.text


async def test_participants_no_event_selected(client, maker):
    resp = await client.get("/participants")
    assert resp.status_code == 200


async def test_winners_page_renders(client, maker):
    event_id = await make_event(maker)
    resp = await client.get("/winners", params={"event_id": event_id})
    assert resp.status_code == 200
    assert "Разыграть" in resp.text


async def test_draw_winners_count_and_only_paid(client, maker):
    event_id = await make_event(
        maker, winners_count=2, number_min=1, number_max=20
    )

    participant1_id = await make_participant(maker, event_id, vk_user_id=111)
    purchase1_id = await make_purchase(
        maker, event_id, participant1_id, status=PurchaseStatus.approved
    )
    for n in range(1, 6):
        await make_poster_number(maker, event_id, participant1_id, purchase1_id, n)

    participant2_id = await make_participant(maker, event_id, vk_user_id=222)
    purchase2_id = await make_purchase(
        maker, event_id, participant2_id, status=PurchaseStatus.manual_review
    )
    for n in (100, 101):
        await make_poster_number(maker, event_id, participant2_id, purchase2_id, n)

    resp = await client.post(f"/winners/{event_id}/draw")
    assert resp.status_code == 200
    assert resp.text.count("winner-row") == 2


async def test_draw_fewer_when_not_enough_paid(client, maker):
    event_id = await make_event(
        maker, winners_count=2, number_min=1, number_max=20
    )

    participant_id = await make_participant(maker, event_id)
    purchase_id = await make_purchase(
        maker, event_id, participant_id, status=PurchaseStatus.approved
    )
    await make_poster_number(maker, event_id, participant_id, purchase_id, 1)

    resp = await client.post(f"/winners/{event_id}/draw")
    assert resp.status_code == 200
    assert resp.text.count("winner-row") == 1
