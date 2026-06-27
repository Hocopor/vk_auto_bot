import random
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Event, PosterNumber


class NumbersExhausted(Exception):
    """Свободных номеров в диапазоне мероприятия меньше, чем требуется."""

    def __init__(self, event_id: int, requested: int, available: int):
        self.event_id, self.requested, self.available = event_id, requested, available
        super().__init__(f"event {event_id}: requested {requested}, available {available}")


def count_posters(amount, price) -> int:
    """Сколько билетов покрывает сумма amount по цене price. Без исключений."""
    if amount is None or price is None:
        return 0
    price = Decimal(price)
    amount = Decimal(amount)
    if price <= 0 or amount < price:
        return 0
    return int(amount // price)


async def assigned_numbers(session: AsyncSession, event_id: int) -> set[int]:
    result = await session.execute(
        select(PosterNumber.number).where(PosterNumber.event_id == event_id)
    )
    return set(result.scalars().all())


async def free_count(session: AsyncSession, event_id: int) -> int:
    event = await session.get(Event, event_id)
    total = event.number_max - event.number_min + 1
    occupied = await assigned_numbers(session, event_id)
    return total - len(occupied)


async def assign_unique(
    session: AsyncSession,
    event_id: int,
    participant_id: int,
    purchase_id: int,
    count: int,
) -> list[int]:
    if count <= 0:
        return []

    event = await session.get(Event, event_id)
    occupied = await assigned_numbers(session, event_id)
    free = set(range(event.number_min, event.number_max + 1)) - occupied

    if len(free) < count:
        raise NumbersExhausted(event_id, count, len(free))

    chosen = sorted(random.sample(sorted(free), count))

    for n in chosen:
        session.add(
            PosterNumber(
                event_id=event_id,
                participant_id=participant_id,
                purchase_id=purchase_id,
                number=n,
            )
        )

    await session.flush()
    return chosen


async def assigned_count_for_purchase(session: AsyncSession, purchase_id: int) -> int:
    """Сколько номеров фактически присвоено данной покупке (по PosterNumber)."""
    result = await session.execute(
        select(func.count())
        .select_from(PosterNumber)
        .where(PosterNumber.purchase_id == purchase_id)
    )
    return int(result.scalar_one())


async def free_numbers(session: AsyncSession, purchase_id: int) -> int:
    result = await session.execute(
        select(PosterNumber).where(PosterNumber.purchase_id == purchase_id)
    )
    rows = result.scalars().all()
    count = len(rows)
    if count:
        await session.execute(
            delete(PosterNumber).where(PosterNumber.purchase_id == purchase_id)
        )
        await session.flush()
    return count
