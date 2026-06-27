"""Abuse-гейт авто-подтверждения: глобальный дедуп чеков + свежесть даты.

См. PLAN.md Фаза 8 §8.3.3. Используется в purchases.decide_after_ocr.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.models import Purchase, PurchaseStatus
from app.core.services import app_settings as s

# Статусы, при которых чужой Purchase считается «живым» дублем. Отклонённые/
# отозванные НЕ блокируют (повторная отправка после отказа может быть легитимной).
_ACTIVE_DUP_STATUSES = (
    PurchaseStatus.pending_ocr,
    PurchaseStatus.auto_confirmed,
    PurchaseStatus.manual_review,
    PurchaseStatus.approved,
)

DEFAULT_MAX_AGE_DAYS = 3


async def is_duplicate_global(
    session: AsyncSession,
    receipt_hash: str | None,
    receipt_signature: str | None = None,
    *,
    exclude_purchase_id: int | None = None,
) -> bool:
    """Есть ли в ЛЮБОМ мероприятии другой «живой» Purchase с тем же хэшем файла
    ИЛИ той же подписью-реквизитом. Отклонённые/отозванные не считаются."""
    conds = []
    if receipt_hash:
        conds.append(Purchase.receipt_hash == receipt_hash)
    if receipt_signature:
        conds.append(Purchase.receipt_signature == receipt_signature)
    if not conds:
        return False
    stmt = (
        select(Purchase.id)
        .where(or_(*conds), Purchase.status.in_(_ACTIVE_DUP_STATUSES))
        .limit(1)
    )
    if exclude_purchase_id is not None:
        stmt = stmt.where(Purchase.id != exclude_purchase_id)
    result = await session.execute(stmt)
    return result.first() is not None


def is_date_fresh(
    receipt_date: date | None,
    now: datetime | None = None,
    *,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    allow_without_date: bool = False,
) -> bool:
    """Свежа ли дата чека: не в будущем и не старше max_age_days (по локальной TZ).
    Если даты нет — результат определяется allow_without_date."""
    if receipt_date is None:
        return allow_without_date
    now = now or datetime.now(timezone.utc)
    today = timeutil.to_local(now).date()
    if receipt_date > today:
        return False
    if (today - receipt_date).days > max_age_days:
        return False
    return True


async def load_gate_config(session: AsyncSession) -> tuple[int, bool]:
    """Читает настройки abuse-гейта из app_settings: (max_age_days, allow_without_date)."""
    raw_age = await s.get_setting(session, s.KEY_RECEIPT_MAX_AGE_DAYS)
    try:
        max_age_days = int(raw_age) if raw_age is not None else DEFAULT_MAX_AGE_DAYS
    except (TypeError, ValueError):
        max_age_days = DEFAULT_MAX_AGE_DAYS
    if max_age_days < 0:
        max_age_days = DEFAULT_MAX_AGE_DAYS
    allow_without_date = (
        await s.get_setting(session, s.KEY_AUTOCONFIRM_WITHOUT_DATE)
    ) == "true"
    return max_age_days, allow_without_date
