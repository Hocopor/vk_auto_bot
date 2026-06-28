import random
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Event, PosterNumber, Purchase, PurchaseStatus

# Статусы покупок, которые «живые» и претендуют на номера (бронируют ёмкость),
# пока номера им фактически не присвоены. rejected/revoked сюда НЕ входят.
OPEN_PURCHASE_STATUSES = (
    PurchaseStatus.pending_ocr,
    PurchaseStatus.manual_review,
    PurchaseStatus.approved,
    PurchaseStatus.auto_confirmed,
)


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


async def assigned_count(session: AsyncSession, event_id: int) -> int:
    """Сколько номеров уже фактически присвоено в мероприятии (COUNT PosterNumber)."""
    result = await session.execute(
        select(func.count())
        .select_from(PosterNumber)
        .where(PosterNumber.event_id == event_id)
    )
    return int(result.scalar_one())


async def reserved_open(session: AsyncSession, event_id: int) -> int:
    """Прогнозная бронь: сумма потребности «живых» покупок без присвоенных номеров.

    На каждую такую покупку резервируем max(1, posters_count) — минимум 1 номер,
    даже если кол-во билетов ещё не посчитано (pending_ocr). Это закрывает окно
    между «участник оплатил» и «админ одобрил», чтобы не налить оплат сверх ёмкости.
    """
    result = await session.execute(
        select(Purchase.posters_count).where(
            Purchase.event_id == event_id,
            Purchase.status.in_(OPEN_PURCHASE_STATUSES),
            Purchase.numbers_assigned.is_(False),
        )
    )
    return sum(max(1, pc or 0) for pc in result.scalars().all())


async def event_capacity(session: AsyncSession, event_id: int) -> dict:
    """Ёмкость мероприятия по номерам.

    capacity        — всего номеров в диапазоне;
    assigned        — уже присвоено;
    reserved        — прогнозная бронь открытых покупок без номеров;
    free            — capacity - assigned (фактически свободные сейчас);
    free_projected  — capacity - assigned - reserved (с учётом брони; по нему
                      бот решает, принимать ли новых участников).
    """
    event = await session.get(Event, event_id)
    if event is None:
        return {"capacity": 0, "assigned": 0, "reserved": 0, "free": 0, "free_projected": 0}
    capacity = event.number_max - event.number_min + 1
    assigned = await assigned_count(session, event_id)
    reserved = await reserved_open(session, event_id)
    return {
        "capacity": capacity,
        "assigned": assigned,
        "reserved": reserved,
        "free": capacity - assigned,
        "free_projected": capacity - assigned - reserved,
    }


async def assign_available(
    session: AsyncSession,
    event_id: int,
    participant_id: int,
    purchase_id: int,
    count: int,
) -> list[int]:
    """Присваивает ДО count свободных номеров (частичное присвоение, не всё-или-ничего).

    Возвращает фактически присвоенные номера (может быть меньше count или пусто).
    Используется воркером: при нехватке выдаём сколько есть, остаток уходит в
    shortfall (а не в вечный ретрай, как было с assign_unique)."""
    if count <= 0:
        return []

    event = await session.get(Event, event_id)
    occupied = await assigned_numbers(session, event_id)
    free = sorted(set(range(event.number_min, event.number_max + 1)) - occupied)

    take = min(count, len(free))
    if take <= 0:
        return []

    chosen = sorted(random.sample(free, take))
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


async def purchase_numbers(session: AsyncSession, purchase_id: int) -> list[int]:
    """Все номера, присвоенные покупке, по возрастанию."""
    result = await session.execute(
        select(PosterNumber.number)
        .where(PosterNumber.purchase_id == purchase_id)
        .order_by(PosterNumber.number)
    )
    return list(result.scalars().all())


async def recover_event_capacity(session: AsyncSession, event_id: int) -> int:
    """Освободилась ёмкость (reject/расширение диапазона) → дать воркеру дозаполнить
    покупки с недостачей. Сбрасываем у одобренных shortfall-покупок флаг
    numbers_assigned, чтобы воркер переобработал и доприсвоил номера (он считает
    needed = posters_count - уже_присвоено, поэтому двойного присвоения не будет).

    Возвращает число затронутых покупок."""
    result = await session.execute(
        select(Purchase).where(
            Purchase.event_id == event_id,
            Purchase.status == PurchaseStatus.approved,
            Purchase.numbers_shortfall.is_not(None),
        )
    )
    purchases = result.scalars().all()
    for p in purchases:
        p.numbers_assigned = False
    if purchases:
        await session.flush()
    return len(purchases)


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
