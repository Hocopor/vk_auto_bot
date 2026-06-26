"""Sync approved poster numbers to a Google Sheet."""

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.models import PosterNumber, Purchase, PurchaseStatus

logger = logging.getLogger(__name__)

HEADER = ["Номер", "Имя", "Оплачено"]
PAID_MARK = "✅"


def extract_sheet_id(url: str) -> str:
    """Extract spreadsheet ID from various Google Sheets URL formats.

    Supports:
    - https://docs.google.com/spreadsheets/d/{ID}/edit
    - https://docs.google.com/spreadsheets/d/{ID}
    - https://docs.google.com/spreadsheets/d/{ID}/edit?usp=sharing
    """
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
    if not match:
        raise ValueError(f"Cannot extract spreadsheet ID from URL: {url}")
    return match.group(1)


def reader_url(url: str) -> str:
    """Read-only вид Google-таблицы для участников (без права редактирования)."""
    sheet_id = extract_sheet_id(url)
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/preview"


async def collect_approved_records(
    session: AsyncSession, event_id: int
) -> list[tuple[int, str | None]]:
    """Fetch approved poster numbers with participant names for an event."""
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


async def sync_event_to_sheet(
    session: AsyncSession,
    event_id: int,
    google_sheet_url: str,
) -> None:
    """Sync approved poster numbers to the given Google Sheet.

    - If sheet is empty -> create header row + data
    - If sheet has header -> verify format, correct if needed, then upsert data
    - Extra rows beyond data are deleted
    - Best-effort: catches and logs all errors, never raises
    """
    from app.sheets.client import get_client

    try:
        records = await collect_approved_records(session, event_id)
        sheet_id = extract_sheet_id(google_sheet_url)
        gc = get_client()
        spreadsheet = gc.open_by_key(sheet_id)
        ws = spreadsheet.sheet1

        existing = ws.get_all_values()

        if not existing or existing[0] != HEADER:
            ws.clear()
            ws.append_row(HEADER, value_input_option="RAW")

        new_rows = [[str(num), name or "", PAID_MARK] for num, name in records]

        if not new_rows:
            if len(existing) > 1:
                ws.delete_rows(2, len(existing))
            return

        current_data_rows = max(0, len(existing) - 1) if existing else 0

        if current_data_rows > len(new_rows):
            ws.delete_rows(len(new_rows) + 2, len(existing))
            current_data_rows = len(new_rows)

        if new_rows:
            if current_data_rows == 0:
                ws.append_rows(new_rows, value_input_option="RAW")
            else:
                cell_range = f"A2:C{len(new_rows) + 1}"
                ws.update(cell_range, new_rows, value_input_option="RAW")

        logger.info(
            "Synced %d records to Google Sheet %s for event %s",
            len(new_rows),
            sheet_id,
            event_id,
        )

    except Exception:
        logger.exception(
            "Failed to sync event %s to Google Sheet %s",
            event_id,
            google_sheet_url,
        )
