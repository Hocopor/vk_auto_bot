import asyncio
import logging
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.db import async_session_maker
from app.core.models import Purchase, PurchaseStatus
from app.core.placeholders import format_numbers, render
from app.core.services import public_table
from app.core.services.numbers import NumbersExhausted, assign_unique, count_posters
from app.core.services.participants import resolve_public_name

logger = logging.getLogger(__name__)

SendMessage = Callable[[int, str], Awaitable[None]]


def _resolve_sheet_url(event) -> str:
    if event.google_sheet_url:
        from app.sheets.sync import reader_url

        try:
            return reader_url(event.google_sheet_url)
        except Exception:
            logger.exception(
                "reader_url failed for event %s, fallback to public table", event.id
            )
    return public_table.public_table_url(event.id)


async def process_pending(
    session: AsyncSession,
    *,
    send_message: SendMessage,
) -> int:
    """Найти оплаченные покупки без номеров, присвоить номера и уведомить участника.

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
            "name": resolve_public_name(participant) or "",
            "numbers": format_numbers(numbers),
            "count": len(numbers),
            "price": event.price,
            "sheet_url": _resolve_sheet_url(event),
            "event_name": event.name,
        }

        if event.send_after_payment:
            text = render(event.msg_after_payment, ctx)
            try:
                await send_message(participant.vk_user_id, text)
            except Exception:
                logger.exception(
                    "Failed to send after-payment message to vk_user_id=%s",
                    participant.vk_user_id,
                )

        if (
            event.send_need_contacts
            and (not participant.provided_name or not participant.phone)
            and event.msg_need_contacts
        ):
            try:
                await send_message(
                    participant.vk_user_id, render(event.msg_need_contacts, ctx)
                )
            except Exception:
                logger.exception(
                    "Failed to send need-contacts message to vk_user_id=%s",
                    participant.vk_user_id,
                )

        # Sync to Google Sheet if configured
        if event.google_sheet_url:
            try:
                from app.sheets.sync import sync_event_to_sheet

                await sync_event_to_sheet(
                    session, event.id, event.google_sheet_url
                )
            except Exception:
                logger.exception(
                    "Google Sheets sync failed for event %s (best-effort, continuing)",
                    event.id,
                )

        processed += 1

    await session.commit()
    return processed


def make_real_callbacks(bot):
    async def _send(vk_user_id: int, text: str) -> None:
        await bot.api.messages.send(peer_id=vk_user_id, message=text, random_id=0)

    return _send


async def run_once(bot) -> int:
    send = make_real_callbacks(bot)
    async with async_session_maker() as session:
        return await process_pending(session, send_message=send)


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
