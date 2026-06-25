"""Чистая бизнес-логика диалога бота. НЕ импортирует vkbottle — тестируется на SQLite."""

import hashlib
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import BotDialogState, Event, Purchase, PurchaseStatus
from app.core.services.participants import parse_name_and_phone, upsert_participant
from app.core.services.purchases import decide_after_ocr

logger = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")


def normalize(text: str | None) -> str:
    """Нижний регистр, обрезка, схлопывание пробелов."""
    return _WS_RE.sub(" ", (text or "").lower().strip())


def is_keyword_match(text: str, keyword: str) -> bool:
    """Проверяет, встречается ли keyword в text как целое слово/фраза (без учёта регистра)."""
    norm_keyword = normalize(keyword)
    if not norm_keyword:
        return False
    pattern = r"(?<!\w)" + re.escape(norm_keyword) + r"(?!\w)"
    return bool(re.search(pattern, normalize(text)))


def _as_naive_utc(dt: datetime) -> datetime:
    """Приводит datetime к naive UTC (для безопасного сравнения aware/naive)."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def is_event_open(event: Event, now: datetime) -> bool:
    """Активно ли событие сейчас (учитывая сроки)."""
    if not event.is_active:
        return False

    now_naive = _as_naive_utc(now)

    if event.starts_at is not None:
        starts_naive = _as_naive_utc(event.starts_at)
        if now_naive < starts_naive:
            return False

    if event.ends_at is not None:
        ends_naive = _as_naive_utc(event.ends_at)
        if now_naive > ends_naive:
            return False

    return True


async def find_matching_event(
    session: AsyncSession, text: str, now: datetime | None = None
) -> Event | None:
    """Ищет первое активное и открытое событие, чьё кодовое слово встречается в text."""
    now = now or datetime.now(timezone.utc)
    result = await session.execute(select(Event).where(Event.is_active.is_(True)))
    events = result.scalars().all()
    for event in events:
        if is_keyword_match(text, event.keyword) and is_event_open(event, now):
            return event
    return None


async def set_dialog(session: AsyncSession, vk_user_id: int, event_id: int) -> None:
    """Устанавливает/обновляет состояние диалога пользователя (на какое событие он отвечает)."""
    result = await session.execute(
        select(BotDialogState).where(BotDialogState.vk_user_id == vk_user_id)
    )
    state = result.scalar_one_or_none()
    if state is None:
        state = BotDialogState(vk_user_id=vk_user_id, event_id=event_id)
        session.add(state)
    else:
        state.event_id = event_id
    await session.flush()


async def get_dialog_event_id(session: AsyncSession, vk_user_id: int) -> int | None:
    """Возвращает event_id текущего диалога пользователя, либо None."""
    result = await session.execute(
        select(BotDialogState).where(BotDialogState.vk_user_id == vk_user_id)
    )
    state = result.scalar_one_or_none()
    return state.event_id if state is not None else None


async def clear_dialog(session: AsyncSession, vk_user_id: int) -> None:
    """Удаляет состояние диалога пользователя, если оно есть."""
    result = await session.execute(
        select(BotDialogState).where(BotDialogState.vk_user_id == vk_user_id)
    )
    state = result.scalar_one_or_none()
    if state is not None:
        await session.delete(state)
        await session.flush()


def compute_receipt_hash(content: bytes) -> str:
    """SHA-256 хэш содержимого файла чека (для дедупликации)."""
    return hashlib.sha256(content).hexdigest()


async def is_duplicate_receipt(session: AsyncSession, event_id: int, receipt_hash: str) -> bool:
    """Проверяет, был ли уже загружен чек с таким хэшем в рамках события."""
    result = await session.execute(
        select(Purchase).where(
            Purchase.event_id == event_id,
            Purchase.receipt_hash == receipt_hash,
        )
    )
    return result.scalar_one_or_none() is not None


async def resolve_event_for_receipt(
    session: AsyncSession, vk_user_id: int, now: datetime | None = None
) -> Event | None:
    """Определяет, к какому событию относится присланный пользователем чек (по контексту диалога)."""
    now = now or datetime.now(timezone.utc)
    event_id = await get_dialog_event_id(session, vk_user_id)
    if event_id is None:
        return None
    event = await session.get(Event, event_id)
    if event is None or not is_event_open(event, now):
        return None
    return event


async def process_receipt(
    session: AsyncSession,
    *,
    event: Event,
    vk_user_id: int,
    vk_name: str | None = None,
    vk_link: str | None = None,
    message_text: str = "",
    receipt_file_path: str | None,
    receipt_hash: str | None,
    ocr_amount=None,
    ocr_raw_text: str | None = None,
    ocr_confidence: float | None = None,
    recipient_found: bool = False,
    is_duplicate: bool = False,
) -> Purchase:
    """Фиксирует участника и создаёт Purchase, решая её статус (или manual_review при дубле)."""
    name, phone = parse_name_and_phone(message_text)

    participant = await upsert_participant(
        session,
        event.id,
        vk_user_id,
        vk_name=vk_name,
        vk_link=vk_link,
        provided_name=name,
        phone=phone,
    )

    purchase = Purchase(
        event_id=event.id,
        participant_id=participant.id,
        receipt_file_path=receipt_file_path,
        receipt_hash=receipt_hash,
        ocr_raw_text=ocr_raw_text,
        ocr_amount=ocr_amount,
        ocr_confidence=ocr_confidence,
        status=PurchaseStatus.pending_ocr,
    )
    session.add(purchase)
    await session.flush()

    if is_duplicate:
        logger.warning(
            "Possible duplicate receipt: event_id=%s vk_user_id=%s hash=%s",
            event.id,
            vk_user_id,
            receipt_hash,
        )
        purchase.status = PurchaseStatus.manual_review
        purchase.moderated_by = None
        await session.flush()
    else:
        await decide_after_ocr(session, purchase, event, recipient_found)

    return purchase
