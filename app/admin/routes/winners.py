from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import OptionalInt, get_session, require_login
from app.admin.templating import templates
from app.core.models import Event
from app.core.services.winners import pick_winners

router = APIRouter()


@router.get("/winners")
async def winners_page(
    request: Request,
    event_id: OptionalInt = None,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    events_result = await session.execute(select(Event).order_by(Event.name))
    events = events_result.scalars().all()

    event = None
    if event_id is not None:
        event = await session.get(Event, event_id)

    return templates.TemplateResponse(
        "winners.html",
        {
            "request": request,
            "user": user,
            "events": events,
            "event_id": event_id,
            "event": event,
            "winners": None,
        },
    )


@router.post("/winners/{event_id}/draw")
async def draw_winners(
    event_id: int,
    request: Request,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    winners = await pick_winners(session, event_id)

    event = await session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Мероприятие не найдено")

    events_result = await session.execute(select(Event).order_by(Event.name))
    events = events_result.scalars().all()

    return templates.TemplateResponse(
        "winners.html",
        {
            "request": request,
            "user": user,
            "events": events,
            "event_id": event_id,
            "event": event,
            "winners": winners,
        },
    )
