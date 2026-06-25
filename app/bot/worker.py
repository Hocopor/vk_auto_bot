import asyncio
import logging
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.db import async_session_maker
from app.core.models import Event, Purchase, PurchaseStatus
from app.core.placeholders import format_numbers, render
from app.core.services.numbers import NumbersExhausted, assign_unique, count_posters
from app.sheets import sync as sheets_sync

logger = logging.getLogger(__name__)

SendMessage = Callable[[int, str], Awaitable[None]]
SyncSheet = Callable[[Event, list[tuple[int, str | None]]], Awaitable[None]]


async def process_pending(
    session: AsyncSession,
    *,
    send_message: SendMessage,
    sync_sheet: SyncSheet,
) -> int:
    """Найти оплаченные покупки без номеров, присвоить номера, уведомить и зеркалить в Sheets.

    Возвращает количество обработанных (numbers_assigned выставлен) покупок.
    """
    stmt = (
        select(Purchase)
        .where(
            Purchase.status == PurchaseStatus.approved,
            Purchase.numbers_assigned.is_(False),
        )
        .options(selectinload(Purchase.event), selectinload(Purchase.participant))
    )
    result = await session.execute(stmt)
    purchases = result.scalars().all()

    processed = 0

    for purchase in purchases:
        event = purchase.event
        participant = purchase.participant

        count = purchase.posters_count or count_posters(purchase.amount, event.price)
        if count <= 0:
            logger.warning(
                "Purchase %s has non-positive posters count (%s), skipping",
                purchase.id,
                count,
            )
            continue

        try:
            numbers = await assign_unique(
                session, event.id, participant.id, purchase.id, count
            )
        except NumbersExhausted as e:
            logger.error(
                "Numbers exhausted for event %s: requested %s, available %s — ADMIN ALERT",
                e.event_id,
                e.requested,
                e.available,
            )
            continue

        purchase.numbers_assigned = True
        await session.flush()

        ctx = {
            "name": participant.provided_name or "",
            "numbers": format_numbers(numbers),
            "count": len(numbers),
            "price": event.price,
            "sheet_url": (
                f"https://docs.google.com/spreadsheets/d/{event.sheet_id}"
                if event.sheet_id
                else ""
            ),
        }

        text = render(event.msg_after_payment, ctx)

        try:
            await send_message(participant.vk_user_id, text)
        except Exception:
            logger.exception(
                "Failed to send after-payment message to vk_user_id=%s",
                participant.vk_user_id,
            )

        if (not participant.provided_name or not participant.phone) and event.msg_need_contacts:
            try:
                await send_message(
                    participant.vk_user_id, render(event.msg_need_contacts, ctx)
                )
            except Exception:
                logger.exception(
                    "Failed to send need-contacts message to vk_user_id=%s",
                    participant.vk_user_id,
                )

        records = [(n, participant.provided_name) for n in numbers]
        try:
            await sync_sheet(event, records)
        except Exception:
            logger.exception("Failed to sync sheet for event %s", event.id)

        processed += 1

    await session.commit()
    return processed


def make_real_callbacks(bot):
    async def _send(vk_user_id: int, text: str) -> None:
        await bot.api.messages.send(peer_id=vk_user_id, message=text, random_id=0)

    async def _sync(event, records) -> None:
        if event.sheet_id:
            await sheets_sync.add_rows(event.sheet_id, records)

    return _send, _sync


async def run_once(bot) -> int:
    send, sync = make_real_callbacks(bot)
    async with async_session_maker() as session:
        return await process_pending(session, send_message=send, sync_sheet=sync)


async def worker_loop(bot, stop_event: asyncio.Event | None = None) -> None:
    logger.info("Worker started, interval=%ss", settings.worker_interval_sec)
    while stop_event is None or not stop_event.is_set():
        try:
            n = await run_once(bot)
            if n:
                logger.info("Worker assigned numbers for %s purchase(s)", n)
        except Exception:
            logger.exception("Worker iteration failed")
        await asyncio.sleep(settings.worker_interval_sec)
