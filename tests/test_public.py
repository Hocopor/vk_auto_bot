from decimal import Decimal

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.admin.deps import get_session
from app.admin.main import app
from app.core import models  # noqa: F401  (наполняет Base.metadata)
from app.core.db import Base
from app.core.models import Event, Participant, PosterNumber, Purchase, PurchaseStatus


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

    app.dependency_overrides[get_session] = _get_session_override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


async def _seed(maker, *, number=7, name="Иван", status=PurchaseStatus.approved):
    async with maker() as session:
        event = Event(
            name="Розыгрыш Тест", keyword="тест", is_active=True, price=Decimal("250"),
            number_min=1, number_max=100, winners_count=1,
        )
        session.add(event)
        await session.flush()
        participant = Participant(event_id=event.id, vk_user_id=111, provided_name=name)
        session.add(participant)
        await session.flush()
        purchase = Purchase(
            event_id=event.id, participant_id=participant.id, status=status,
            numbers_assigned=True,
        )
        session.add(purchase)
        await session.flush()
        session.add(PosterNumber(
            event_id=event.id, participant_id=participant.id,
            purchase_id=purchase.id, number=number,
        ))
        await session.commit()
        return event.id


async def test_public_page_lists_paid_numbers(client, maker):
    event_id = await _seed(maker, number=7, name="Иван")
    resp = await client.get(f"/p/{event_id}")
    assert resp.status_code == 200
    assert "Розыгрыш Тест" in resp.text
    assert "Иван" in resp.text
    assert "7" in resp.text
    # страница публичная — отдаётся без авторизации (не редиректит на /login)
    assert "/login" not in resp.headers.get("location", "")


async def test_public_page_excludes_non_approved(client, maker):
    event_id = await _seed(maker, number=42, name="Пётр", status=PurchaseStatus.manual_review)
    resp = await client.get(f"/p/{event_id}")
    assert resp.status_code == 200
    assert "Пётр" not in resp.text
    assert "<b id=\"count\">0</b>" in resp.text


async def test_public_page_404_for_missing_event(client):
    resp = await client.get("/p/999999")
    assert resp.status_code == 404
