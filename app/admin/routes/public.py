"""Публичная (без авторизации) страница со списком участников мероприятия.

`GET /p/{event_id}` — живая таблица оплаченных номеров из Postgres. Любой может
открыть из браузера и найти себя по имени или номеру (поиск на странице).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import get_session
from app.admin.templating import templates
from app.core.models import Event
from app.core.services import public_table

router = APIRouter()


@router.get("/p/{event_id:int}")
async def public_table_page(
    event_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    event = await session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Список не найден")
    records = await public_table.collect_records(session, event_id)
    return templates.TemplateResponse(
        "public_table.html",
        {
            "request": request,
            "event": event,
            "records": records,
            "count": len(records),
            "paid_mark": public_table.PAID_MARK,
        },
    )
