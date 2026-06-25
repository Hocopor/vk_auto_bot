from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Event, Purchase, PurchaseStatus
from app.core.services.numbers import count_posters, free_numbers


def evaluate_payment(amount, price, recipient_found: bool) -> bool:
    """True если сумма покрывает хотя бы один билет, кратна цене и получатель верный."""
    if amount is None or price is None:
        return False
    amount = Decimal(amount)
    price = Decimal(price)
    if price <= 0:
        return False
    return bool(amount >= price and (amount % price == 0) and recipient_found)


async def decide_after_ocr(
    session: AsyncSession,
    purchase: Purchase,
    event: Event,
    recipient_found: bool,
) -> PurchaseStatus:
    """Решение о статусе покупки после OCR (§8.2)."""
    source_amount = purchase.ocr_amount

    if event.auto_confirm and evaluate_payment(source_amount, event.price, recipient_found):
        purchase.status = PurchaseStatus.approved
        purchase.amount = source_amount
        purchase.posters_count = count_posters(source_amount, event.price)
    else:
        purchase.status = PurchaseStatus.manual_review

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
    if purchase.amount is not None and event is not None and not purchase.posters_count:
        purchase.posters_count = count_posters(purchase.amount, event.price)
    await session.flush()


async def reject(session: AsyncSession, purchase: Purchase, moderated_by: str | None = None) -> None:
    purchase.status = PurchaseStatus.rejected
    purchase.moderated_by = moderated_by
    await session.flush()


async def revoke(session: AsyncSession, purchase: Purchase, moderated_by: str | None = None) -> int:
    n = await free_numbers(session, purchase.id)
    purchase.status = PurchaseStatus.revoked
    purchase.numbers_assigned = False
    purchase.moderated_by = moderated_by
    await session.flush()
    return n
