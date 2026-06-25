import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.models import Event, PosterNumber, Purchase, PurchaseStatus
from app.sheets.client import get_client

logger = logging.getLogger(__name__)

HEADER = ["Номер", "Имя", "Оплачено"]
PAID_MARK = "✅"


def build_rows(records: list[tuple[int, str | None]]) -> list[list]:
    """Сформировать строки публичной таблицы из списка (number, name).

    Возвращает [HEADER] + отсортированные по номеру строки [number, name or "", PAID_MARK].
    Чистая функция, без сети.
    """
    sorted_records = sorted(records, key=lambda r: r[0])
    rows: list[list] = [HEADER]
    for number, name in sorted_records:
        rows.append([number, name or "", PAID_MARK])
    return rows


async def create_sheet(title: str) -> str | None:
    """Создать новую Google-таблицу с шапкой и публичным доступом на чтение.

    Возвращает sheet_id или None при ошибке.
    """
    try:
        def _create() -> str:
            client = get_client()
            sh = client.create(title)
            ws = sh.sheet1
            ws.update([HEADER])
            sh.share(None, perm_type="anyone", role="reader")
            return sh.id

        return await asyncio.to_thread(_create)
    except Exception:
        logger.exception("Failed to create sheet %r", title)
        return None


async def rebuild(sheet_id: str, records: list[tuple[int, str | None]]) -> bool:
    """Полностью пересобрать лист из переданных записей.

    Возвращает True при успехе, False при ошибке.
    """
    try:
        def _rebuild() -> None:
            client = get_client()
            sh = client.open_by_key(sheet_id)
            ws = sh.sheet1
            ws.clear()
            ws.update(build_rows(records))

        await asyncio.to_thread(_rebuild)
        return True
    except Exception:
        logger.exception("Failed to rebuild sheet %s", sheet_id)
        return False


async def add_rows(sheet_id: str, records: list[tuple[int, str | None]]) -> bool:
    """Дописать строки в конец листа (без шапки).

    Возвращает True при успехе, False при ошибке.
    """
    try:
        def _add() -> None:
            client = get_client()
            sh = client.open_by_key(sheet_id)
            ws = sh.sheet1
            rows = [[number, name or "", PAID_MARK] for number, name in records]
            ws.append_rows(rows)

        await asyncio.to_thread(_add)
        return True
    except Exception:
        logger.exception("Failed to add rows to sheet %s", sheet_id)
        return False


async def remove_rows(sheet_id: str, numbers: list[int]) -> bool:
    """Удалить строки, где значение в колонке «Номер» входит в numbers.

    Реализовано через полное перечитывание/перезапись листа (надёжно, без проблем
    со сдвигом индексов при удалении нескольких строк подряд).
    Возвращает True при успехе, False при ошибке.
    """
    try:
        def _remove() -> None:
            client = get_client()
            sh = client.open_by_key(sheet_id)
            ws = sh.sheet1
            all_values = ws.get_all_values()
            numbers_set = set(numbers)
            kept_rows = []
            for row in all_values[1:]:
                if not row:
                    continue
                try:
                    row_number = int(row[0])
                except (ValueError, IndexError):
                    continue
                if row_number in numbers_set:
                    continue
                kept_rows.append(row)
            ws.clear()
            ws.update([HEADER] + kept_rows)

        await asyncio.to_thread(_remove)
        return True
    except Exception:
        logger.exception("Failed to remove rows from sheet %s", sheet_id)
        return False


async def share_url(sheet_id: str) -> str:
    """Публичная ссылка на таблицу. Чистая строка, без сети, не падает."""
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}"


async def delete_sheet(sheet_id: str) -> bool:
    """Удалить Google-таблицу (при каскадном удалении мероприятия).

    Возвращает True при успехе, False при ошибке. Падение API не критично.
    """
    try:
        def _delete() -> None:
            client = get_client()
            client.del_spreadsheet(sheet_id)

        await asyncio.to_thread(_delete)
        return True
    except Exception:
        logger.exception("Failed to delete sheet %s", sheet_id)
        return False


async def collect_event_records(session: AsyncSession, event_id: int) -> list[tuple[int, str | None]]:
    """Собрать (number, participant.provided_name) для всех PosterNumber события,
    привязанных к покупкам со статусом approved. Это «истина» для зеркала в Sheets.
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
        (pn.number, pn.participant.provided_name if pn.participant else None)
        for pn in poster_numbers
    ]


async def rebuild_event_sheet(session: AsyncSession, event_id: int) -> bool:
    """Пересобрать публичную таблицу события из БД (источник истины — Postgres)."""
    event = await session.get(Event, event_id)
    if event is None or event.sheet_id is None:
        logger.warning("Event %s has no sheet_id, skipping rebuild", event_id)
        return False
    records = await collect_event_records(session, event_id)
    return await rebuild(event.sheet_id, records)
