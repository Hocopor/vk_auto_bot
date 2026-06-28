"""Фаза 9 — контроль лимита номеров (overselling) и гейтинг бота по исчерпанию."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bot import dialog
from app.core import models  # noqa: F401  (наполняет Base.metadata)
from app.core.db import Base
from app.core.models import Event, Participant, PosterNumber, Purchase, PurchaseStatus
from app.core.services import numbers
from app.core.services.purchases import reject


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def make_event(session, *, keyword="роза", number_min=1, number_max=10):
    event = Event(
        name="Розыгрыш",
        keyword=keyword,
        is_active=True,
        price=Decimal("250"),
        number_min=number_min,
        number_max=number_max,
        winners_count=1,
        auto_confirm=False,
    )
    session.add(event)
    await session.flush()
    return event


async def add_purchase(
    session, event, *, status=PurchaseStatus.approved, posters_count=2,
    numbers_assigned=False, vk_user_id=555,
):
    participant = Participant(event_id=event.id, vk_user_id=vk_user_id, provided_name="Иван")
    session.add(participant)
    await session.flush()
    purchase = Purchase(
        event_id=event.id,
        participant_id=participant.id,
        amount=Decimal("500"),
        posters_count=posters_count,
        status=status,
        numbers_assigned=numbers_assigned,
    )
    session.add(purchase)
    await session.flush()
    return participant, purchase


# --- 9.1 модель ёмкости -----------------------------------------------------

async def test_event_capacity_counts_assigned_and_reserved(session):
    event = await make_event(session, number_min=1, number_max=10)  # capacity 10
    # одна одобренная покупка на 3 билета, ещё без номеров → бронь 3
    await add_purchase(session, event, posters_count=3, vk_user_id=1)
    # одна pending без posters_count → бронь минимум 1
    await add_purchase(
        session, event, status=PurchaseStatus.pending_ocr, posters_count=None, vk_user_id=2
    )
    # 2 уже присвоенных номера (другой покупке)
    _, assigned_p = await add_purchase(
        session, event, posters_count=2, numbers_assigned=True, vk_user_id=3
    )
    session.add_all([
        PosterNumber(event_id=event.id, participant_id=assigned_p.participant_id, purchase_id=assigned_p.id, number=1),
        PosterNumber(event_id=event.id, participant_id=assigned_p.participant_id, purchase_id=assigned_p.id, number=2),
    ])
    await session.flush()

    cap = await numbers.event_capacity(session, event.id)
    assert cap["capacity"] == 10
    assert cap["assigned"] == 2
    assert cap["reserved"] == 3 + 1  # 3 за одобренную + 1 минимум за pending
    assert cap["free"] == 8
    assert cap["free_projected"] == 10 - 2 - 4  # = 4


async def test_rejected_purchases_do_not_reserve(session):
    event = await make_event(session, number_min=1, number_max=5)
    await add_purchase(session, event, status=PurchaseStatus.rejected, posters_count=3, vk_user_id=1)
    cap = await numbers.event_capacity(session, event.id)
    assert cap["reserved"] == 0
    assert cap["free_projected"] == 5


# --- 9.2 гейтинг бота -------------------------------------------------------

async def test_find_matching_event_returns_event_when_capacity_free(session):
    await make_event(session, keyword="роза", number_min=1, number_max=5)
    await session.commit()
    found = await dialog.find_matching_event(session, "хочу розА пожалуйста")
    assert found is not None


async def test_find_matching_event_silent_when_exhausted(session):
    event = await make_event(session, keyword="роза", number_min=1, number_max=1)  # cap 1
    # одна открытая покупка бронирует единственный номер → free_projected 0
    await add_purchase(session, event, posters_count=1, vk_user_id=1)
    await session.commit()
    found = await dialog.find_matching_event(session, "роза")
    assert found is None  # бот молчит


async def test_is_event_accepting_false_when_full(session):
    event = await make_event(session, number_min=1, number_max=2)  # capacity 2
    participant, purchase = await add_purchase(
        session, event, posters_count=2, numbers_assigned=True, vk_user_id=1
    )
    # оба номера фактически присвоены → assigned 2, free_projected 0
    session.add_all([
        PosterNumber(event_id=event.id, participant_id=participant.id, purchase_id=purchase.id, number=1),
        PosterNumber(event_id=event.id, participant_id=participant.id, purchase_id=purchase.id, number=2),
    ])
    await session.flush()
    assert await dialog.is_event_accepting(session, event) is False


# --- 9.3 / инвариант: частичное присвоение не превышает ёмкость --------------

async def test_assign_available_is_partial_and_capped(session):
    event = await make_event(session, number_min=1, number_max=3)
    participant, purchase = await add_purchase(session, event, posters_count=5)
    got = await numbers.assign_available(session, event.id, participant.id, purchase.id, 5)
    assert len(got) == 3  # выдано только сколько есть
    assert all(1 <= n <= 3 for n in got)
    # инвариант: присвоенных не больше ёмкости
    cap = await numbers.event_capacity(session, event.id)
    assert cap["assigned"] <= cap["capacity"]


async def test_assign_available_no_double_assign_on_topup(session):
    event = await make_event(session, number_min=1, number_max=5)
    participant, purchase = await add_purchase(session, event, posters_count=5)
    first = await numbers.assign_available(session, event.id, participant.id, purchase.id, 2)
    assert len(first) == 2
    # дозаполнить оставшиеся 3
    already = await numbers.assigned_count_for_purchase(session, purchase.id)
    second = await numbers.assign_available(session, event.id, participant.id, purchase.id, 5 - already)
    assert len(second) == 3
    all_nums = await numbers.purchase_numbers(session, purchase.id)
    assert len(all_nums) == 5
    assert len(set(all_nums)) == 5  # без дублей


# --- 9.5 восстановление ёмкости --------------------------------------------

async def test_reject_frees_numbers_and_recovers_shortfall(session):
    event = await make_event(session, number_min=1, number_max=3)
    # purchase A занимает все 3 номера
    pa, purchase_a = await add_purchase(session, event, posters_count=3, vk_user_id=1)
    nums_a = await numbers.assign_available(session, event.id, pa.id, purchase_a.id, 3)
    purchase_a.numbers_assigned = True
    # purchase B одобрена, но номеров не осталось → shortfall
    pb, purchase_b = await add_purchase(session, event, posters_count=2, vk_user_id=2)
    got_b = await numbers.assign_available(session, event.id, pb.id, purchase_b.id, 2)
    assert got_b == []
    purchase_b.numbers_assigned = True
    purchase_b.numbers_shortfall = 2
    await session.flush()

    # reject A → освобождает 3 номера и восстанавливает ёмкость (сбрасывает латч B)
    freed = await reject(session, purchase_a, moderated_by="admin")
    assert freed == 3
    await session.refresh(purchase_b)
    assert purchase_b.numbers_assigned is False  # B переоткрыт для воркера
