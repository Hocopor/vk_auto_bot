"""Публичная таблица участников — отдаётся самим сервером (без Google).

Источник истины — Postgres. Страница `/p/{event_id}` показывает живой список
оплаченных номеров: «Номер | Имя | Оплачено». Никаких внешних API.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.models import PosterNumber, Purchase, PurchaseStatus
from app.core.services.participants import resolve_public_name

HEADER = ("Номер", "Имя", "Оплачено")
PAID_MARK = "✅"


async def collect_records(
    session: AsyncSession, event_id: int
) -> list[tuple[int, str | None]]:
    """(number, provided_name) для всех номеров события с покупкой approved.

    Отсортировано по номеру. Только оплаченные (присвоенные) номера, без пустых строк.
    """
    stmt = (
        select(PosterNumber)
        .join(Purchase, PosterNumber.purchase_id == Purchase.id)
        .where(
            PosterNumber.event_id == event_id,
            Purchase.status == PurchaseStatus.approved,
        )
        .options(selectinload(PosterNumber.participant))
        .order_by(PosterNumber.number)
    )
    result = await session.execute(stmt)
    poster_numbers = result.scalars().all()
    return [
        (pn.number, resolve_public_name(pn.participant) if pn.participant else None)
        for pn in poster_numbers
    ]


def public_table_url(event_id: int) -> str:
    """Абсолютная ссылка на публичную страницу (для сообщений бота).

    База берётся из настройки `public_base_url` (.env). Если она не задана —
    возвращается относительный путь (в сообщении бесполезен, но не падает).
    """
    base = (settings.public_base_url or "").rstrip("/")
    if base:
        return f"{base}/p/{event_id}"
    return f"/p/{event_id}"
