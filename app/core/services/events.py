from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.defaults import DEFAULT_TEXTS
from app.core.models import Event


async def create_event(
    session: AsyncSession,
    *,
    name: str,
    keyword: str,
    price,
    number_min: int,
    number_max: int,
    winners_count: int = 1,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    expected_recipient: str | None = None,
    auto_confirm: bool = False,
    qr_image_path: str | None = None,
    msg_instruction: str | None = None,
    msg_after_payment: str | None = None,
    msg_receipt_received: str | None = None,
    msg_need_contacts: str | None = None,
    is_active: bool = True,
    send_instruction: bool = True,
    send_qr: bool = True,
    send_receipt_received: bool = True,
    send_after_payment: bool = True,
    send_need_contacts: bool = False,
) -> Event:
    keyword = keyword.strip().lower()

    event = Event(
        name=name,
        keyword=keyword,
        is_active=is_active,
        price=price,
        number_min=number_min,
        number_max=number_max,
        winners_count=winners_count,
        starts_at=starts_at,
        ends_at=ends_at,
        msg_instruction=msg_instruction or DEFAULT_TEXTS["msg_instruction"],
        msg_after_payment=msg_after_payment or DEFAULT_TEXTS["msg_after_payment"],
        msg_receipt_received=msg_receipt_received or DEFAULT_TEXTS["msg_receipt_received"],
        msg_need_contacts=msg_need_contacts or DEFAULT_TEXTS["msg_need_contacts"],
        qr_image_path=qr_image_path,
        auto_confirm=auto_confirm,
        expected_recipient=expected_recipient,
        sheet_id=None,
        send_instruction=send_instruction,
        send_qr=send_qr,
        send_receipt_received=send_receipt_received,
        send_after_payment=send_after_payment,
        send_need_contacts=send_need_contacts,
    )
    session.add(event)
    await session.flush()
    return event


async def delete_event(session: AsyncSession, event_id: int) -> bool:
    result = await session.execute(
        select(Event)
        .where(Event.id == event_id)
        .options(
            selectinload(Event.participants),
            selectinload(Event.purchases),
            selectinload(Event.poster_numbers),
        )
    )
    event = result.scalar_one_or_none()
    if event is None:
        return False
    await session.delete(event)
    await session.flush()
    return True


async def set_active(session: AsyncSession, event_id: int, active: bool) -> None:
    event = await session.get(Event, event_id)
    event.is_active = active
    await session.flush()
