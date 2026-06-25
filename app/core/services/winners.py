import random

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Event, PosterNumber, Purchase, PurchaseStatus


async def pick_winners(session: AsyncSession, event_id: int) -> list[PosterNumber]:
    """Случайно выбирает winners_count уникальных номеров из присвоенных (approved) покупок."""
    event = await session.get(Event, event_id)

    result = await session.execute(
        select(PosterNumber)
        .join(Purchase, PosterNumber.purchase_id == Purchase.id)
        .where(
            PosterNumber.event_id == event_id,
            Purchase.status == PurchaseStatus.approved,
        )
        .options(selectinload(PosterNumber.participant))
    )
    all_numbers = list(result.scalars().all())

    if len(all_numbers) <= event.winners_count:
        random.shuffle(all_numbers)
        return all_numbers

    return random.sample(all_numbers, event.winners_count)
