from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Event, Purchase, PurchaseStatus
from app.core.services import abuse
from app.core.services.numbers import (
    assigned_count_for_purchase,
    count_posters,
    free_numbers,
    recover_event_capacity,
)


def evaluate_payment(amount, price, recipient_found: bool) -> bool:
    """True если сумма покрывает хотя бы один билет и получатель верный.
    Кратности НЕ требуем — кол-во билетов = floor(amount/price)."""
    if amount is None or price is None:
        return False
    amount = Decimal(amount)
    price = Decimal(price)
    if price <= 0:
        return False
    return bool(amount >= price and recipient_found)


def can_approve(purchase: Purchase, event: Event) -> bool:
    """Можно ли одобрять: указана сумма, и она покрывает хотя бы один билет."""
    if purchase.amount is None or event is None:
        return False
    return count_posters(purchase.amount, event.price) >= 1


async def decide_after_ocr(
    session: AsyncSession,
    purchase: Purchase,
    event: Event,
    recipient_found: bool,
    *,
    is_duplicate: bool = False,
    receipt_date=None,
    now=None,
    max_age_days: int = abuse.DEFAULT_MAX_AGE_DAYS,
    allow_without_date: bool = False,
) -> PurchaseStatus:
    """Решение о статусе покупки после OCR (§8.2/§8.3).

    Авто-аппрув только если: auto_confirm И сумма покрывает билет И получатель найден,
    И НЕ сработал abuse-гейт (глобальный/локальный дубль, несвежая дата). Иначе —
    manual_review (с флагом needs_attention, если завернул именно abuse-гейт)."""
    now = now or datetime.now(timezone.utc)
    source_amount = purchase.ocr_amount

    payment_ok = event.auto_confirm and evaluate_payment(
        source_amount, event.price, recipient_found
    )
    if not payment_ok:
        purchase.status = PurchaseStatus.manual_review
        await session.flush()
        return purchase.status

    flagged = (
        is_duplicate
        or await abuse.is_duplicate_global(
            session,
            purchase.receipt_hash,
            purchase.receipt_signature,
            exclude_purchase_id=purchase.id,
        )
        or not abuse.is_date_fresh(
            receipt_date,
            now,
            max_age_days=max_age_days,
            allow_without_date=allow_without_date,
        )
    )
    if flagged:
        purchase.status = PurchaseStatus.manual_review
        purchase.needs_attention = True
    else:
        purchase.status = PurchaseStatus.approved
        purchase.amount = source_amount
        purchase.posters_count = count_posters(source_amount, event.price)

    await session.flush()
    return purchase.status


async def set_amount(session: AsyncSession, purchase: Purchase, amount, event: Event) -> None:
    purchase.amount = amount
    purchase.posters_count = count_posters(amount, event.price)
    await session.flush()


async def approve(
    session: AsyncSession,
    purchase: Purchase,
    moderated_by: str | None = None,
    event: Event | None = None,
) -> None:
    purchase.status = PurchaseStatus.approved
    purchase.moderated_by = moderated_by
    if purchase.amount is not None and event is not None:
        purchase.posters_count = count_posters(purchase.amount, event.price)
    # Re-delivery safety: флаг стоит, но номеров фактически нет (после reject/смены
    # статусов) — сбросить, иначе воркер навсегда пропустит покупку.
    if purchase.numbers_assigned:
        if await assigned_count_for_purchase(session, purchase.id) == 0:
            purchase.numbers_assigned = False
    await session.flush()


async def reject(session: AsyncSession, purchase: Purchase, moderated_by: str | None = None) -> int:
    """Отклонить покупку: освободить присвоенные номера, статус rejected, снять флаг.
    Раньше это делал revoke (но со статусом revoked) — теперь объединено в reject."""
    n = await free_numbers(session, purchase.id)
    purchase.status = PurchaseStatus.rejected
    purchase.numbers_assigned = False
    purchase.numbers_shortfall = None
    purchase.moderated_by = moderated_by
    await session.flush()
    # Освободилась ёмкость — дать воркеру дозаполнить покупки с недостачей в этом
    # мероприятии (Фаза 9, восстановление ёмкости).
    await recover_event_capacity(session, purchase.event_id)
    return n
